"""kaizen pretooluse_trace — consolidated hot-path trace for the
PreToolUse hook. Reads stdin once, extracts tool_name + ident +
session_id, calls trace.append_event directly. One python3 spawn
instead of the prior 4 (~120ms saved per fire on a hook that fires
on every tool call).

Bypass: KAIZEN_METRICS_DISABLE=1 (the hook checks this BEFORE
spawning python3, so we never even start when disabled).

Tool-specific ident extraction mirrors the prior shell+python
extraction. Bash is skipped here because pretooluse-bash-gate.sh
traces it separately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_TOOL_IDENT_EXTRACTORS = {
    "Skill":        lambda inp: inp.get("skill", ""),
    "Edit":         lambda inp: inp.get("file_path", ""),
    "Write":        lambda inp: inp.get("file_path", ""),
    "Read":         lambda inp: inp.get("file_path", ""),
    "NotebookEdit": lambda inp: inp.get("file_path", ""),
    "Glob":         lambda inp: inp.get("pattern", ""),
    "Grep":         lambda inp: inp.get("pattern", ""),
    "Agent":        lambda inp: inp.get("subagent_type", inp.get("description", "")),
    "TaskCreate":   lambda inp: inp.get("subject", ""),
    "WebFetch":     lambda inp: inp.get("url", ""),
}


def _extract_ident(tool_name: str, tool_input: dict) -> str:
    """Per-tool ident extraction. MCP tools use their full name as
    the ident (mcp__server__tool is already specific). Everything
    else routes through _TOOL_IDENT_EXTRACTORS — falls back to ""."""
    if tool_name.startswith("mcp__"):
        return tool_name
    extractor = _TOOL_IDENT_EXTRACTORS.get(tool_name)
    if extractor is None:
        return ""
    try:
        return str(extractor(tool_input) or "")[:120]
    except Exception:
        return ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = event.get("tool_name", "")
    # Skip Bash (pretooluse-bash-gate.sh traces it separately) and
    # empty tool_name (malformed event — nothing to trace).
    if not tool_name or tool_name == "Bash":
        return 0

    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    ident = _extract_ident(tool_name, tool_input)
    sid = event.get("session_id", "") or ""

    # Import trace.append_event directly — no subprocess. One process
    # for the entire hot path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import trace as _trace
    except ImportError:
        return 0

    record: dict = {
        "ts": _trace._now_iso(),
        "src": "hook",
        "evt": f"PreToolUse-{tool_name}",
        "tool": tool_name,
    }
    if sid:
        record["sid"] = sid
    if ident:
        record["data"] = {"ident": ident}

    _trace.append_event(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
