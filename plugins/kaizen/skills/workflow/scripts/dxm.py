"""kaizen-dxm — deus-ex-machina: live session-state mirror.

Fast-store companion to Claude Code's session JSONL. The JSONL lags
3–15s because CC buffers per-turn; dxm captures events with sub-
millisecond write latency via hook-driven shell append, so any consumer
(scaffold, verify, MCP clients, downstream tools) can query "what just
happened" in real-time.

## Storage

    ~/.claude/.kaizen/dxm/events-<session_id>.jsonl   ← per-session events
    ~/.claude/.kaizen/dxm/sessions.jsonl              ← session lineage

Env: KAIZEN_DXM_DIR overrides root. KAIZEN_DXM_DISABLE=1 → all
capture+query operations no-op (still exit 0 so hook flow never breaks).

## Subcommands

    capture           — stdin event JSON → append to events-<sid>.jsonl
                        {session_id, evt_type, tool_name?, payload?}
                        ts_unix added by capture (sub-millisecond precision)
    now    --session S — current-state snapshot:
                        {session_id, event_count, by_tool, last_event_at,
                         lag_seconds, parent_session_id?}
    tail   --session S [--limit N] [--since-unix T]
                        — most recent events (default 20, newest last)
    link   --parent P --child C
                        — record parent→child session continuity

## Why JSONL not SQLite

Hot path is hook-driven; shell append is sub-ms (no python3 spawn).
Reads are bounded (most queries want last N events of one session).
A SQLite cross-session index can be a phase-2 add when queries grow
beyond per-session tail.

## Iron-law interaction

- bin-wrapper-per-cli — bin/kaizen-dxm wraps this script
- plugin-manifest-permissions — explicit perm entry in plugin.json
- hook-bypass-knob — KAIZEN_DXM_DISABLE=1 honored
- sandbox-tests — KAIZEN_DXM_DIR env sandboxes per-test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-dxm", tool_version="1.0.0")


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _disabled() -> bool:
    return os.environ.get("KAIZEN_DXM_DISABLE") == "1"


def _events_path(session_id: str) -> Path:
    return _dxm_dir() / f"events-{session_id}.jsonl"


def _sessions_path() -> Path:
    return _dxm_dir() / "sessions.jsonl"


# ─── capture ─────────────────────────────────────────────────────────


def _cmd_capture(args) -> int:
    if _disabled():
        return 0
    raw = sys.stdin.read() if not args.payload else args.payload
    try:
        rec = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[kaizen-dxm capture] payload not JSON: {exc}",
              file=sys.stderr)
        return 2
    if not isinstance(rec, dict):
        print("[kaizen-dxm capture] payload must be a JSON object",
              file=sys.stderr)
        return 2

    sid = rec.get("session_id")
    evt_type = rec.get("evt_type")
    if not sid or not isinstance(sid, str):
        print("[kaizen-dxm capture] session_id required (non-empty string)",
              file=sys.stderr)
        return 2
    if not evt_type or not isinstance(evt_type, str):
        print("[kaizen-dxm capture] evt_type required (non-empty string)",
              file=sys.stderr)
        return 2

    # Stamp ts_unix sub-millisecond; preserve other fields verbatim.
    rec.setdefault("ts_unix", time.time())
    line = json.dumps(rec, separators=(",", ":"), default=str) + "\n"

    target = _events_path(sid)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Single open+append. Race-free for single-writer-per-line semantics
    # because Linux append on a file < PIPE_BUF is atomic.
    with target.open("a", encoding="utf-8") as f:
        f.write(line)

    if args.json:
        _emit({"session_id": sid, "evt_type": evt_type,
                "ts_unix": rec["ts_unix"],
                "events_path": str(target)}, verdict="green")
    return 0


# ─── now (snapshot) ──────────────────────────────────────────────────


def _read_events(session_id: str) -> list[dict]:
    """Read all events for a session. Returns [] when file missing."""
    path = _events_path(session_id)
    if not path.is_file():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _read_parent(session_id: str) -> Optional[str]:
    """Return the parent_session_id linked to `session_id`, if any."""
    path = _sessions_path()
    if not path.is_file():
        return None
    # Newest link wins
    parent = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("child_session_id") == session_id:
                parent = rec.get("parent_session_id")
    return parent


def _cmd_now(args) -> int:
    if _disabled():
        if args.json:
            _emit({"disabled": True}, verdict="yellow")
        return 0
    events = _read_events(args.session)
    by_tool: Counter[str] = Counter()
    last_ts = 0.0
    for e in events:
        tn = e.get("tool_name")
        if tn:
            by_tool[tn] += 1
        ts = e.get("ts_unix")
        if isinstance(ts, (int, float)) and ts > last_ts:
            last_ts = float(ts)

    lag = (time.time() - last_ts) if last_ts > 0 else 0.0
    data = {
        "session_id":         args.session,
        "event_count":        len(events),
        "by_tool":            dict(by_tool),
        "last_event_at_unix": last_ts if last_ts > 0 else None,
        "lag_seconds":        round(lag, 4) if last_ts > 0 else None,
        "parent_session_id":  _read_parent(args.session),
    }
    if args.json:
        verdict = "green" if events else "yellow"
        _emit(data, verdict=verdict, counts={"events": len(events)})
    else:
        print(f"[kaizen-dxm now] session={args.session}")
        print(f"  events:        {len(events)}")
        print(f"  by_tool:       {dict(by_tool)}")
        if last_ts > 0:
            print(f"  last_event_at: {last_ts:.3f} ({lag:.2f}s ago)")
        if data["parent_session_id"]:
            print(f"  parent:        {data['parent_session_id']}")
    return 0


# ─── tail ────────────────────────────────────────────────────────────


def _cmd_tail(args) -> int:
    if _disabled():
        if args.json:
            _emit({"disabled": True, "events": []}, verdict="yellow")
        return 0

    # Rolling-window flags. Validate non-negative.
    for flag, val in (("--back", args.back),
                       ("--window-from", args.window_from),
                       ("--window-to", args.window_to)):
        if val is not None and val < 0:
            print(f"[kaizen-dxm tail] {flag} must be >= 0 (got {val})",
                  file=sys.stderr)
            return 2

    events = _read_events(args.session)
    now = time.time()

    # Compute the time bounds. Precedence:
    #   --window-from / --window-to (explicit half-open range from past)
    #   --back (events from (now - back) to now)
    #   --since-unix (absolute lower bound)
    lower = None  # ts_unix > lower
    upper = None  # ts_unix <= upper

    if args.window_from is not None or args.window_to is not None:
        if args.window_from is not None:
            lower = now - args.window_from
        if args.window_to is not None:
            upper = now - args.window_to
    elif args.back is not None:
        lower = now - args.back
    elif args.since_unix is not None:
        lower = args.since_unix

    if lower is not None or upper is not None:
        def _in_window(e: dict) -> bool:
            ts = e.get("ts_unix")
            if not isinstance(ts, (int, float)):
                return False
            if lower is not None and ts <= lower:
                return False
            if upper is not None and ts > upper:
                return False
            return True
        events = [e for e in events if _in_window(e)]

    if args.limit and args.limit > 0:
        events = events[-args.limit:]

    data = {
        "session_id": args.session,
        "events":     events,
        "count":      len(events),
    }
    if args.json:
        _emit(data, counts={"events": len(events)})
    else:
        print(f"[kaizen-dxm tail] session={args.session} ({len(events)} events)")
        for e in events:
            ts = e.get("ts_unix", 0)
            print(f"  {ts:.3f}  {e.get('evt_type')}  tool={e.get('tool_name','-')}")
    return 0


# ─── link ────────────────────────────────────────────────────────────


# ─── replay (install-day blindspot fix) ──────────────────────────────


def _attachment_to_event(att: dict, session_id: str) -> Optional[dict]:
    """Turn a CC attachment record (with hookEvent) into a dxm event
    dict, or None when the attachment isn't a hook record we capture."""
    hook_event = att.get("hookEvent")
    if not hook_event:
        return None

    # Convert CC attachment timestamp to ts_unix (best-effort). The
    # surrounding JSONL line carries `timestamp` as the authoritative
    # ISO 8601; caller will pass that in via `_replay_record`.
    rec: dict = {
        "session_id": session_id,
        "evt_type":   hook_event,
    }
    # Tool name lives in hookName as "<Event>:<Tool>" — split on colon
    hook_name = att.get("hookName", "")
    if ":" in hook_name:
        tool = hook_name.split(":", 1)[1]
        if tool:
            rec["tool_name"] = tool
    # Optional rich fields preserved from the attachment
    for src, dst in (("toolUseID",  "tool_use_id"),
                      ("durationMs", "duration_ms"),
                      ("exitCode",   "exit_code"),
                      ("command",    "command")):
        if src in att and att[src] is not None:
            rec[dst] = att[src]
    return rec


def _iso_to_unix(iso: str) -> Optional[float]:
    """Best-effort ISO 8601 → unix float conversion."""
    if not isinstance(iso, str) or not iso:
        return None
    try:
        import datetime as _dt
        # Handle trailing Z
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(iso).timestamp()
    except (ValueError, TypeError):
        return None


def _cmd_replay(args) -> int:
    """Walk a Claude Code session JSONL and synthesize dxm events.

    Used to backfill events when dxm is installed mid-session (CC
    only registers hooks at session start, so install-day sessions
    miss live capture). After replay, kaizen-dxm now / tail return
    the full session history."""
    if _disabled():
        return 0
    src = Path(args.jsonl).expanduser()
    if not src.is_file():
        msg = f"jsonl not found: {src}"
        if args.json:
            _emit({"error": msg}, verdict="red")
        else:
            print(f"[kaizen-dxm replay] {msg}", file=sys.stderr)
        return 1

    target = _events_path(args.session)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not args.no_truncate and target.exists():
        target.unlink()

    synthesized = 0
    with src.open("r", encoding="utf-8") as f, \
         target.open("a", encoding="utf-8") as out:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "attachment":
                continue
            att = o.get("attachment") or {}
            if not isinstance(att, dict):
                continue
            evt = _attachment_to_event(att, args.session)
            if evt is None:
                continue
            # Carry through the JSONL line's timestamp as ts_unix
            ts_unix = _iso_to_unix(o.get("timestamp", ""))
            if ts_unix is None:
                ts_unix = time.time()
            evt["ts_unix"] = ts_unix
            out.write(json.dumps(evt, separators=(",", ":"),
                                  default=str) + "\n")
            synthesized += 1

    data = {
        "session_id":       args.session,
        "source_jsonl":     str(src.resolve()),
        "events_path":      str(target.resolve()),
        "synthesized_count": synthesized,
        "truncated":        not args.no_truncate,
    }
    if args.json:
        verdict = "green" if synthesized > 0 else "yellow"
        _emit(data, verdict=verdict, counts={"synthesized": synthesized})
    else:
        mode = "truncated+replayed" if not args.no_truncate else "appended"
        print(f"[kaizen-dxm replay] {mode} {synthesized} events for "
              f"session={args.session}")
        print(f"  source: {src.resolve()}")
        print(f"  target: {target.resolve()}")
    return 0


def _cmd_link(args) -> int:
    if _disabled():
        return 0
    rec = {
        "ts_unix":           time.time(),
        "parent_session_id": args.parent,
        "child_session_id":  args.child,
    }
    path = _sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    if args.json:
        _emit(rec, verdict="green")
    else:
        print(f"[kaizen-dxm link] {args.parent} → {args.child}")
    return 0


# ─── argparse ────────────────────────────────────────────────────────


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-dxm",
        description="deus-ex-machina: live session-state mirror over "
                    "Claude Code's JSONL.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("capture", help="append an event to a session's stream")
    sc.add_argument("--payload", default=None,
                     help="inline JSON payload (overrides stdin)")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_cmd_capture)

    sn = sub.add_parser("now", help="current snapshot for a session")
    sn.add_argument("--session", required=True)
    sn.add_argument("--json", action="store_true")
    sn.set_defaults(func=_cmd_now)

    st = sub.add_parser("tail", help="most-recent events for a session")
    st.add_argument("--session", required=True)
    st.add_argument("--limit", type=int, default=20)
    st.add_argument("--since-unix", type=float, default=None,
                     help="filter events strictly after this unix timestamp")
    st.add_argument("--back", type=float, default=None,
                     help="rolling window: events from (now - SECONDS) to now")
    st.add_argument("--window-from", type=float, default=None,
                     help="window lower bound: SECONDS ago (exclusive)")
    st.add_argument("--window-to", type=float, default=None,
                     help="window upper bound: SECONDS ago (inclusive). "
                          "Use with --window-from for a middle slice.")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=_cmd_tail)

    sl = sub.add_parser("link", help="record a parent→child session continuity edge")
    sl.add_argument("--parent", required=True)
    sl.add_argument("--child", required=True)
    sl.add_argument("--json", action="store_true")
    sl.set_defaults(func=_cmd_link)

    sr = sub.add_parser(
        "replay",
        help="backfill dxm events from a CC session JSONL — fixes the "
             "install-day blindspot where hooks aren't registered yet",
    )
    sr.add_argument("--session", required=True,
                     help="session_id to populate (must match the source JSONL)")
    sr.add_argument("--jsonl", required=True,
                     help="path to the source CC session JSONL")
    sr.add_argument("--no-truncate", action="store_true",
                     help="append to existing events file instead of "
                          "truncating (default: truncate first)")
    sr.add_argument("--json", action="store_true")
    sr.set_defaults(func=_cmd_replay)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
