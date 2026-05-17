"""kaizen session_mode — record + read the session intake choice.

At SessionStart the intake hook asks "loop, workflow, or neither?"
The user's answer routes future agent behavior:

  loop      → agent runs /kaizen:loop with its prompt
  workflow  → agent runs /workflow with a routine
  neither   → no kaizen-loop / no workflow scaffolding

This module is the persistence layer — small enough to live in one
file (KISS). Storage is a JSON file at `.kaizen/session-mode.json`
(override with KAIZEN_SESSION_MODE_PATH for tests).

CLI:

    session_mode.py set <mode> [--skills DRY,KISS,...] [--session-id ID]
    session_mode.py get [--json]
    session_mode.py clear
    session_mode.py exists                  # exit 0 iff a mode is set

Modes: loop | workflow | neither.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path


_VALID_MODES = ("loop", "workflow", "neither")


def _state_path() -> Path:
    env = os.environ.get("KAIZEN_SESSION_MODE_PATH")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path(".kaizen") / "session-mode.json"


def _iso_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state() -> dict | None:
    path = _state_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(data: dict) -> bool:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def _cmd_set(args) -> int:
    if args.mode not in _VALID_MODES:
        sys.stderr.write(
            f"[kaizen-session-mode set] invalid mode {args.mode!r}; "
            f"choose from {', '.join(_VALID_MODES)}\n"
        )
        return 2
    state = {
        "mode":       args.mode,
        "set_at":     _iso_now(),
        "session_id": args.session_id or "",
        "skills":     [s.strip() for s in (args.skills or "").split(",") if s.strip()],
    }
    if not write_state(state):
        sys.stderr.write("[kaizen-session-mode set] write failed\n")
        return 1
    print(json.dumps(state))
    return 0


def _cmd_get(args) -> int:
    state = read_state()
    if state is None:
        if args.json:
            print(json.dumps({"mode": None}))
        return 1
    if args.json:
        print(json.dumps(state))
    else:
        print(state.get("mode", ""))
    return 0


def _cmd_clear(args) -> int:
    path = _state_path()
    try:
        path.unlink(missing_ok=True)
        return 0
    except OSError:
        return 1


def _cmd_exists(args) -> int:
    return 0 if read_state() is not None else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-session-mode",
                                  description="Record / read session intake mode.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("set", help="record the mode for this session")
    ps.add_argument("mode", choices=_VALID_MODES)
    ps.add_argument("--skills", default="",
                     help="comma-separated discipline tags (dry,kiss,tdd,solid,...)")
    ps.add_argument("--session-id", default="",
                     help="optional Claude Code session-id pin")
    ps.set_defaults(func=_cmd_set)

    pg = sub.add_parser("get", help="print the active mode")
    pg.add_argument("--json", action="store_true",
                     help="emit full state record as JSON")
    pg.set_defaults(func=_cmd_get)

    pc = sub.add_parser("clear", help="remove the state file")
    pc.set_defaults(func=_cmd_clear)

    pe = sub.add_parser("exists", help="exit 0 iff a mode is set; for hook gating")
    pe.set_defaults(func=_cmd_exists)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
