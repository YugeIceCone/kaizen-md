"""kaizen-intent — declarative intent → action automation.

Sits on top of the dxm event stream + UserPromptSubmit text matching.
Rules live in ``skills/intent/domain/intents.yaml`` (or
``KAIZEN_INTENTS_FILE``) and map triggers to suggested or
auto-runnable actions.

## Sibling layers

  kaizen-trace   = what happened (lifetime log)
  kaizen-dxm     = what's happening now (real-time mirror)
  kaizen-intent  = what should happen (rule-driven automation)

## Subcommands

  list                                 list registered intents
  match  --text TEXT [...]             return all intents matching TEXT
  match  --events-json '[...]'         match against an event list
  suggest --text TEXT [...]            return the BEST match (top confidence)

## Trigger shapes (MVP)

  phrase:
    kind: phrase
    pattern: "let's wrap (this )?up"     # regex
    case_insensitive: true               # optional, default false

  event_pattern:
    kind: event_pattern
    evt_type: PostToolUse
    tool_name: Bash                      # optional filter
    exit_code_nonzero: true              # optional flag
    count_at_least: 3
    window_seconds: 60                   # rolling window

## Action shape

    action:
      suggest: "<one-line hint>"
      subcommand: handoff                # optional — kaizen sub it maps to
      confidence: 0.9                    # 0.0–1.0 for ranking in `suggest`

## Env

  KAIZEN_INTENTS_FILE   override default intents.yaml path
  KAIZEN_INTENT_DISABLE=1   all match/suggest calls no-op
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402
import _dxm_emit  # noqa: E402  — BK-001 per-handler trace events

_emit = _envelope.emitter("kaizen-intent", tool_version="1.0.0")


def _disabled() -> bool:
    return os.environ.get("KAIZEN_INTENT_DISABLE") == "1"


def _intents_path() -> Path:
    env = os.environ.get("KAIZEN_INTENTS_FILE")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    # Default: skills/intent/domain/intents.yaml
    plugin_root = _SCRIPT_DIR.parent.parent.parent  # plugins/kaizen
    return plugin_root / "skills" / "intent" / "domain" / "intents.yaml"


def _load_intents() -> list[dict]:
    path = _intents_path()
    if not path.is_file():
        raise FileNotFoundError(f"intents file not found: {path}")
    try:
        import yaml as _yaml
    except ImportError:
        # Fallback minimal parser — extremely limited; pyyaml is the
        # project convention.
        raise RuntimeError("PyYAML required (pip install pyyaml)")
    with path.open("r", encoding="utf-8") as f:
        data = _yaml.safe_load(f) or {}
    intents = data.get("intents") or []
    if not isinstance(intents, list):
        return []
    return intents


# ─── Matchers ────────────────────────────────────────────────────────


def _phrase_matches(trigger: dict, text: str) -> bool:
    pat = trigger.get("pattern")
    if not pat or not text:
        return False
    flags = re.IGNORECASE if trigger.get("case_insensitive") else 0
    try:
        return bool(re.search(pat, text, flags=flags))
    except re.error:
        return False


def _event_pattern_matches(trigger: dict, events: list[dict]) -> bool:
    """Check if events satisfy the trigger's threshold within window."""
    if not events:
        return False
    evt_type = trigger.get("evt_type")
    tool_name = trigger.get("tool_name")
    exit_code_nonzero = trigger.get("exit_code_nonzero", False)
    count_at_least = int(trigger.get("count_at_least", 1))
    window_seconds = float(trigger.get("window_seconds") or 0)

    # Filter to matching events
    matching: list[dict] = []
    for e in events:
        if evt_type and e.get("evt_type") != evt_type:
            continue
        if tool_name and e.get("tool_name") != tool_name:
            continue
        if exit_code_nonzero:
            ec = e.get("exit_code")
            if ec is None or ec == 0:
                continue
        matching.append(e)

    if len(matching) < count_at_least:
        return False
    if window_seconds <= 0:
        return True  # no window constraint

    # Check whether any sliding window of `count_at_least` consecutive
    # matching events spans <= window_seconds.
    matching.sort(key=lambda e: e.get("ts_unix", 0))
    for i in range(len(matching) - count_at_least + 1):
        span = matching[i + count_at_least - 1]["ts_unix"] - matching[i]["ts_unix"]
        if span <= window_seconds:
            return True
    return False


def _intent_matches(intent: dict, text: str, events: list[dict]) -> bool:
    """An intent fires when ANY of its triggers matches."""
    triggers = intent.get("triggers") or []
    for t in triggers:
        kind = t.get("kind", "phrase")
        if kind == "phrase":
            if text and _phrase_matches(t, text):
                return True
        elif kind == "event_pattern":
            if events and _event_pattern_matches(t, events):
                return True
    return False


def _intent_confidence(intent: dict) -> float:
    return float((intent.get("action") or {}).get("confidence", 0.5))


# ─── CLI handlers ────────────────────────────────────────────────────


def _gather_text(args) -> str:
    if args.text is not None:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _gather_events(args) -> list[dict]:
    if args.events_json:
        try:
            data = json.loads(args.events_json)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


def _cmd_list(args) -> int:
    try:
        intents = _load_intents()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[kaizen-intent list] {exc}", file=sys.stderr)
        return 1
    summary = [
        {
            "id":          i.get("id"),
            "description": i.get("description", ""),
            "trigger_kinds": sorted({
                t.get("kind", "phrase") for t in (i.get("triggers") or [])
            }),
            "confidence":  _intent_confidence(i),
        }
        for i in intents
    ]
    data = {"intents": summary, "count": len(summary)}
    if args.json:
        _emit(data, counts={"intents": len(summary)})
    else:
        print(f"[kaizen-intent list] {len(summary)} intents:")
        for s in summary:
            print(f"  {s['id']:30s}  conf={s['confidence']:.2f}  "
                  f"triggers={s['trigger_kinds']}")
    return 0


def _cmd_match(args) -> int:
    if _disabled():
        if args.json:
            _emit({"disabled": True, "matched": []}, verdict="yellow")
        return 0
    try:
        intents = _load_intents()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[kaizen-intent match] {exc}", file=sys.stderr)
        return 1
    text = _gather_text(args)
    events = _gather_events(args)
    matched: list[dict] = []
    for i in intents:
        if _intent_matches(i, text, events):
            matched.append({
                "id":          i.get("id"),
                "description": i.get("description", ""),
                "confidence":  _intent_confidence(i),
                "action":      i.get("action") or {},
            })
    # Sort by confidence DESC
    matched.sort(key=lambda m: -m["confidence"])
    data = {"matched": matched, "count": len(matched)}
    _dxm_emit.emit_event(
        "intent.match.complete", tool_name="kaizen-intent",
        payload={"matched_count": len(matched),
                  "top_id": matched[0]["id"] if matched else None},
    )
    if args.json:
        verdict = "green" if matched else "yellow"
        _emit(data, verdict=verdict, counts={"matched": len(matched)})
    else:
        if not matched:
            print("[kaizen-intent match] no intents matched")
        else:
            print(f"[kaizen-intent match] {len(matched)} match(es):")
            for m in matched:
                print(f"  {m['id']:30s}  conf={m['confidence']:.2f}  "
                      f"action={(m['action'] or {}).get('suggest', '')[:60]}")
    return 0


def _cmd_suggest(args) -> int:
    if _disabled():
        if args.json:
            _emit({"disabled": True, "intent": None}, verdict="yellow")
        return 0
    try:
        intents = _load_intents()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[kaizen-intent suggest] {exc}", file=sys.stderr)
        return 1
    text = _gather_text(args)
    events = _gather_events(args)
    best = None
    for i in intents:
        if _intent_matches(i, text, events):
            if best is None or _intent_confidence(i) > _intent_confidence(best):
                best = i
    if best is None:
        data = {"intent": None}
    else:
        data = {"intent": {
            "id":          best.get("id"),
            "description": best.get("description", ""),
            "confidence":  _intent_confidence(best),
            "action":      best.get("action") or {},
        }}
    _dxm_emit.emit_event(
        "intent.suggest.complete", tool_name="kaizen-intent",
        payload={"intent_id": (best or {}).get("id"),
                  "confidence": _intent_confidence(best) if best else None},
    )
    if args.json:
        verdict = "green" if best else "yellow"
        _emit(data, verdict=verdict)
    else:
        if best is None:
            print("[kaizen-intent suggest] no intent matched")
        else:
            act = best.get("action") or {}
            print(f"[kaizen-intent suggest] {best.get('id')}  "
                  f"(conf={_intent_confidence(best):.2f})")
            print(f"  → {act.get('suggest', '<no suggestion>')}")
    return 0


def _cmd_scan(args) -> int:
    """Pull last N seconds of events from dxm, run match against them.

    Convenience composition: kaizen-dxm tail --back N + kaizen-intent
    match --events-json — without the agent having to pipe between
    two tools.
    """
    if _disabled():
        if args.json:
            _emit({"disabled": True, "matched": []}, verdict="yellow")
        return 0
    # Read events directly from dxm's per-session file (no subprocess
    # for the hot read).
    dxm_root_env = os.environ.get("KAIZEN_DXM_DIR")
    if dxm_root_env:
        dxm_root = Path(os.path.expandvars(dxm_root_env)).expanduser()
    else:
        dxm_root = Path.home() / ".claude" / ".kaizen" / "dxm"
    events_path = dxm_root / f"events-{args.session}.jsonl"

    events: list[dict] = []
    if events_path.is_file():
        import time as _t
        cutoff = _t.time() - args.back
        try:
            with events_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = e.get("ts_unix")
                    if isinstance(ts, (int, float)) and ts >= cutoff:
                        events.append(e)
        except OSError:
            pass

    try:
        intents = _load_intents()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[kaizen-intent scan] {exc}", file=sys.stderr)
        return 1
    matched: list[dict] = []
    for i in intents:
        if _intent_matches(i, "", events):
            matched.append({
                "id":          i.get("id"),
                "description": i.get("description", ""),
                "confidence":  _intent_confidence(i),
                "action":      i.get("action") or {},
            })
    matched.sort(key=lambda m: -m["confidence"])
    data = {
        "session_id": args.session,
        "back_seconds": args.back,
        "event_count": len(events),
        "matched": matched,
        "count": len(matched),
    }
    _dxm_emit.emit_event(
        "intent.scan.complete", tool_name="kaizen-intent",
        payload={"session_scanned": args.session,
                  "event_count": len(events),
                  "matched_count": len(matched)},
    )
    if args.json:
        verdict = "green" if matched else "yellow"
        _emit(data, verdict=verdict, counts={"matched": len(matched)})
    else:
        print(f"[kaizen-intent scan] session={args.session} "
              f"events={len(events)} matched={len(matched)}")
        for m in matched:
            print(f"  {m['id']:30s}  conf={m['confidence']:.2f}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-intent",
        description="Declarative intent → action automation on top of "
                    "the dxm event stream + text triggers.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sl = sub.add_parser("list", help="list registered intents")
    sl.add_argument("--json", action="store_true")
    sl.set_defaults(func=_cmd_list)

    sm = sub.add_parser("match", help="return all intents matching text/events")
    sm.add_argument("--text", default=None,
                     help="text to match phrase triggers against "
                          "(stdin used if omitted)")
    sm.add_argument("--events-json", default=None,
                     help="JSON array of dxm events to match event_pattern "
                          "triggers against")
    sm.add_argument("--json", action="store_true")
    sm.set_defaults(func=_cmd_match)

    ss = sub.add_parser("suggest", help="return the highest-confidence matching intent")
    ss.add_argument("--text", default=None)
    ss.add_argument("--events-json", default=None)
    ss.add_argument("--json", action="store_true")
    ss.set_defaults(func=_cmd_suggest)

    sc = sub.add_parser(
        "scan",
        help="pull last N seconds of dxm events for a session and run match",
    )
    sc.add_argument("--session", required=True)
    sc.add_argument("--back", type=float, default=60.0,
                     help="rolling window in seconds (default 60)")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_cmd_scan)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
