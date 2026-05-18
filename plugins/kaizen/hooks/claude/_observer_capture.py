"""Observer event capture core — kaizen-md side of the Phase 1.5 build.

Reads CC PostToolUse / PreToolUse JSON from stdin, normalizes to the
canonical observer event shape (matches .kaizen/superpowers/templates/
observer/event.schema.json), atomic-appends to
~/.claude/.kaizen/observer/events.jsonl.

Standalone — no cross-repo import. Duplicates minimal schema-shaping
logic from clever-lama-mcp/src/observer/ingest.py (justified: different
runtime + repo + import context; DRY says extract on the 3rd repetition,
not the 2nd).

Design contract (per user 2026-05-18):
  - PROGRAMMABLE  — normalize_cc_event + capture are pure callables
  - REPRODUCIBLE  — same inputs always produce same dict (test_idempotent_replay)
  - CONSISTENT    — matches detect-nudge / kaizen-learn / kaizen-progress
                    shape (env-overridable sink, atomic append, exit 0,
                    KAIZEN_<X>_DISABLE bypass)
  - DETERMINISTIC — `now` is parameter; no wall-clock peek
  - REUSABLE      — event_kind selector + source registry; adding a new
                    event_kind is a one-line caller change
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _observer_dir() -> Path:
    """~/.claude/.kaizen/observer/ — env-overridable for tests + relocation.

    DRY — delegates to shared _paths.env_overridable_dir. _paths.py
    lives in skills/workflow/scripts/, not on this hook's sys.path
    by default — resolve relative to plugin root.
    """
    import sys as _sys
    scripts_dir = Path(__file__).resolve().parent.parent.parent / "skills" / "workflow" / "scripts"
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    from _paths import env_overridable_dir
    return env_overridable_dir("KAIZEN_OBSERVER_DIR", "observer")


def _sink_path() -> Path:
    return _observer_dir() / "events.jsonl"


def _detect_source() -> tuple[str, str | None]:
    """Returns (source, subagent_type-or-None).

    Source determination:
      - CLAUDE_SUBAGENT_TYPE env set → 'subagent' + the type
      - Default → 'parent'

    Slash-command and MCP sources are detected via tool name in the
    normalize layer (not env-based).
    """
    subagent_type = os.environ.get("CLAUDE_SUBAGENT_TYPE", "").strip()
    if subagent_type:
        return "subagent", subagent_type
    return "parent", None


def _parse_mcp_tool(tool_name: str) -> str | None:
    """Extract the MCP server identifier from a tool name like
    'mcp__clever-lama__parallel_subagents' → 'clever-lama'.
    None when not an mcp__ tool."""
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return None
    parts = tool_name.split("__")
    if len(parts) < 3:
        return None
    return parts[1]


def normalize_cc_event(stdin_text: str, *,
                         event_kind: str,
                         now: str) -> dict[str, Any] | None:
    """Pure normalize. Returns canonical event dict or None on garbage input."""
    if not isinstance(stdin_text, str) or not stdin_text.strip():
        return None
    try:
        payload = json.loads(stdin_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    source, subagent_type = _detect_source()
    tool_name = payload.get("tool_name", "")
    if not isinstance(tool_name, str):
        tool_name = ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    sid = payload.get("session_id", "")
    if not isinstance(sid, str):
        sid = ""

    mcp_server = _parse_mcp_tool(tool_name)
    final_kind = "mcp_tool_call" if mcp_server else event_kind

    event: dict[str, Any] = {
        "ts": now,
        "event_kind": final_kind,
        "source": source,
        "sid": sid,
        "tool": tool_name,
        "params": tool_input,
    }
    if mcp_server:
        event["mcp_server"] = mcp_server
    if subagent_type:
        event["subagent_type"] = subagent_type
    return event


def _atomic_append(sink: Path, event: dict) -> None:
    """Append-only — never reads existing file. Same iron-law as
    kaizen-progress / kaizen-learn. DRY — delegates to shared
    _atomic.atomic_append_line."""
    # _atomic lives in skills/workflow/scripts/, not on this module's sys.path
    # by default — resolve relative to plugin root.
    import sys as _sys
    from pathlib import Path as _Path
    scripts_dir = _Path(__file__).resolve().parent.parent.parent / "skills" / "workflow" / "scripts"
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    from _atomic import atomic_append_line  # noqa: E402
    atomic_append_line(sink, json.dumps(event))


def capture(stdin_text: str, *, event_kind: str, now: str) -> dict:
    """Normalize + append. Never raises.

    Returns:
        {"ok": True, "tool": str}                — wrote one event
        {"ok": False, "reason": str}             — bypassed / garbage / write-fail
    """
    if os.environ.get("KAIZEN_OBSERVER_DISABLE") == "1":
        return {"ok": False, "reason": "disabled"}
    event = normalize_cc_event(stdin_text, event_kind=event_kind, now=now)
    if event is None:
        return {"ok": False, "reason": "invalid_input"}
    try:
        _atomic_append(_sink_path(), event)
    except OSError as e:
        return {"ok": False, "reason": f"write_failed: {e}"}
    return {"ok": True, "tool": event.get("tool", "")}


__all__ = ["normalize_cc_event", "capture"]
