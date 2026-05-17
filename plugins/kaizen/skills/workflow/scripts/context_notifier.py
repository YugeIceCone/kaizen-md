"""kaizen context_notifier — emit dxm event when context-window zone changes.

Reads context state from the active CC session JSONL (via context.py's
from-jsonl source), checks zone, dedupes by scanning dxm's existing
context.warn.* events — only emits when the zone TRANSITIONS to a new
yellow/red.

Designed to be called from Stop or UserPromptSubmit hooks. Cheap
(~50ms). Best-effort: never raises.

## Subcommand

    check [--session SID] [--json]
      → envelope.data: {zone, pct, tokens, limit, last_warn_zone,
                         emitted (bool)}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402
import _dxm_emit  # noqa: E402
import _session_jsonl as _sj  # noqa: E402
import context as _ctx  # noqa: E402

_emit = _envelope.emitter("kaizen-context-notifier", tool_version="1.0.0")


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _latest_warn_zone(session_id: str) -> str | None:
    """Find the most-recent context.warn.* event's zone. Used for
    dedup — we only emit when zone TRANSITIONS, not on every check."""
    path = _dxm_dir() / f"events-{session_id}.jsonl"
    if not path.is_file():
        return None
    last_zone = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                et = e.get("evt_type", "")
                if et.startswith("context.warn."):
                    z = (e.get("payload") or {}).get("zone")
                    if z:
                        last_zone = z
    except OSError:
        return None
    return last_zone


def _cmd_check(args) -> int:
    sid = args.session or _sj.discover_active_session_id()
    if not sid:
        data = {"zone": "unknown", "emitted": False,
                "reason": "no active session"}
        if args.json:
            _emit(data, verdict="yellow")
        return 0

    tokens = _ctx.get_tokens_from_jsonl()
    limit = _ctx.get_limit()
    pct = (tokens * 100 // limit) if tokens is not None else None
    zone = _ctx.zone_of(pct)

    last_warn = _latest_warn_zone(sid)

    emitted = False
    if zone in ("yellow", "red") and zone != last_warn:
        ok = _dxm_emit.emit_event(
            f"context.warn.{zone}",
            tool_name="kaizen-context-notifier",
            payload={"zone": zone, "pct": pct, "tokens": tokens,
                      "limit": limit, "prev_warn_zone": last_warn},
            session_id=sid,
        )
        emitted = bool(ok)

    data = {
        "session_id":     sid,
        "zone":           zone,
        "pct":            pct,
        "tokens":         tokens,
        "limit":          limit,
        "last_warn_zone": last_warn,
        "emitted":        emitted,
    }
    if args.json:
        verdict = ("green" if zone == "green" else
                    "red"   if zone == "red"   else "yellow")
        _emit(data, verdict=verdict)
    else:
        print(f"[kaizen-context-notifier] session={sid} zone={zone} "
              f"pct={pct} emitted={emitted}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-context-notifier",
        description="Emit dxm context.warn.* event when zone transitions.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("check", help="check + emit on transition")
    sc.add_argument("--session", default=None)
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_cmd_check)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
