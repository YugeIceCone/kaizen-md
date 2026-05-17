"""kaizen subagentstop_trace — consolidated SubagentStop trace.

Reads stdin once, extracts subagent identity + verdict + sid, calls
trace.append_event twice (once for the generic SubagentStop event,
once for the SubagentStop-detail event when agent info is present).

Replaces 5 python3 spawns in subagentstop-trace.sh:
  1. _trace.sh subprocess (calls trace.py event)
  2. EXTRA extraction
  3. AGENT field extract
  4. SID field extract
  5. trace.py event subprocess (with --data EXTRA)

Best-effort throughout — never raises.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if os.environ.get("KAIZEN_TRACE_DISABLE") == "1":
        return 0

    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import trace as _trace
    except ImportError:
        return 0

    sid = event.get("session_id") or ""

    # Generic SubagentStop event (mirrors what _trace.sh would have
    # written via the older path).
    rec_generic: dict = {
        "ts":  _trace._now_iso(),
        "src": "hook",
        "evt": "SubagentStop",
    }
    if sid:
        rec_generic["sid"] = sid
    _trace.append_event(rec_generic)

    # Detailed event with subagent identity + status (only when present).
    agent = event.get("subagent_type") or event.get("subagent") or event.get("agent") or ""
    desc = (event.get("description") or event.get("task") or "")
    if not isinstance(desc, str):
        desc = ""
    desc = desc[:80]
    status = event.get("status") or event.get("result_type") or ""

    if agent:
        rec_detail: dict = {
            "ts":   _trace._now_iso(),
            "src":  "hook",
            "evt":  "SubagentStop-detail",
            "tool": str(agent),
            "data": {"agent": agent, "desc": desc, "status": status,
                      "sid": sid},
        }
        if sid:
            rec_detail["sid"] = sid
        _trace.append_event(rec_detail)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
