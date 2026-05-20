#!/usr/bin/env python3
"""kaizen evolution_log — append-only event log for evolve-phase actions.

Port of upstream evolution-log.js. Appends ``<ISO-ts>  <TYPE>  <message>``
lines to ``~/.local/state/remember/evolution.log`` (or ``$XDG_STATE_HOME/
remember/evolution.log``). Used by the evolve/process/remember skill
flows to record PROMOTE/DEMOTE/CONSOLIDATE/REFLECT/STALE/CONTRADICT/
ARCHIVE_CANDIDATE events.

CLI:

    python3 evolution_log.py <TYPE> <message...>
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

VALID_TYPES = frozenset({
    "PROMOTE", "DEMOTE", "CONSOLIDATE", "REFLECT",
    "STALE", "CONTRADICT", "ARCHIVE_CANDIDATE",
})

def default_log_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(state) / "remember" / "evolution.log"

def append_event(event_type: str, message: str,
                 log_path: Path | None = None) -> None:
    """Append one ``<ISO-ts>  <TYPE>  <message>\\n`` line to the log.

    Raises ``ValueError`` on unknown event_type. Creates parent dirs
    on demand. Mirrors upstream evolution-log.js::appendEvent.
    """
    if event_type not in VALID_TYPES:
        raise ValueError(
            f"unknown event type: {event_type} "
            f"(allowed: {', '.join(sorted(VALID_TYPES))})"
        )
    p = log_path or default_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")
    if ts.endswith("+00:00"):
        ts = ts[:-6] + "Z"
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{ts}  {event_type}  {message}\n")

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        sys.stderr.write(
            "Usage: evolution_log.py <TYPE> <message...>\n"
            f"Types: {', '.join(sorted(VALID_TYPES))}\n"
        )
        return 1
    event_type = args[0]
    message = " ".join(args[1:])
    try:
        append_event(event_type, message)
    except ValueError as e:
        sys.stderr.write(f"evolution_log: {e}\n")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
