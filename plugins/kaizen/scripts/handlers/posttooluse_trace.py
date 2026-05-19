"""kaizen posttooluse_trace — consolidated hot-path trace for the
PostToolUse hook. Mirror of pretooluse_trace.py.

Reads stdin once, extracts tool_name + session_id + duration_ms +
ok/err status, calls trace.append_event directly. One python3 spawn
instead of the prior 4.

Bypass: KAIZEN_METRICS_DISABLE=1 (checked by the shell wrapper
before spawning python3).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _extract_duration_ms(event: dict) -> int | None:
    """PostToolUse `duration_ms` may live on the event or nested in
    `tool_response`. Try both."""
    ms = event.get("duration_ms")
    if ms is None:
        resp = event.get("tool_response")
        if isinstance(resp, dict):
            ms = resp.get("duration_ms")
    if ms is None:
        return None
    try:
        return int(ms)
    except (TypeError, ValueError):
        return None


def _extract_ok(event: dict) -> str:
    """Return 'ok' | 'err' | '' based on tool_response shape."""
    resp = event.get("tool_response")
    if not isinstance(resp, dict):
        return ""
    if "error" in resp or resp.get("isError"):
        return "err"
    return "ok"


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = event.get("tool_name", "")
    if not tool_name or tool_name == "Bash":
        return 0

    sid = event.get("session_id", "") or ""
    ms = _extract_duration_ms(event)
    ok = _extract_ok(event)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # MIGRATION BRIDGE — kaizen modules (trace, inbox) still at skills/workflow/scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
    try:
        import trace as _trace
    except ImportError:
        return 0

    record: dict = {
        "ts": _trace._now_iso(),
        "src": "hook",
        "evt": f"PostToolUse-{tool_name}",
        "tool": tool_name,
    }
    if sid:
        record["sid"] = sid
    if ms is not None:
        record["ms"] = ms
    if ok:
        record["data"] = {"result": ok}

    _trace.append_event(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
