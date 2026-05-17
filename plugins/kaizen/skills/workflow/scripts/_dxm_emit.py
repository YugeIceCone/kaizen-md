"""kaizen _dxm_emit — shared emitter for handler-completion dxm events.

DRY: every handler that wants to record "I ran" delegates to one
function. Auto-discovers session_id via _session_jsonl (no per-handler
duplication of the cwd → slug → JSONL chain).

SOLID-SRP: emit_event does ONE thing. Handlers do their work; this
module owns the I/O contract.

KISS: ~40 LOC, one public function, best-effort semantics. Never
raises — handler flow must not break because a trace write failed.

## API

    from _dxm_emit import emit_event

    emit_event("handoff.verify.complete",
                tool_name="kaizen-handoff",
                payload={"verdict": "clean", "files_checked": 12})

    # Auto-discovers session_id from cwd. To override:
    emit_event("...", session_id="explicit-sid")

## Bypass

  KAIZEN_DXM_DISABLE=1  → all calls return False, no file write.

## Output shape

    {
      "ts_unix": 1747461308.876,
      "session_id": "<discovered or supplied>",
      "evt_type": "<your evt_type>",
      "tool_name": "<optional>",
      "payload": {...}            # optional
    }

Appended to ~/.claude/.kaizen/dxm/events-<session_id>.jsonl
(or `$KAIZEN_DXM_DIR/events-<sid>.jsonl`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional


def _dxm_dir() -> Path:
    env = os.environ.get("KAIZEN_DXM_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen" / "dxm"


def _discover_sid() -> Optional[str]:
    """Lazy-import _session_jsonl to avoid module-load-time cycles."""
    try:
        _here = Path(__file__).resolve().parent
        sys.path.insert(0, str(_here))
        import _session_jsonl as _sj
        return _sj.discover_active_session_id()
    except Exception:
        return None


def emit_event(
    evt_type: str,
    *,
    tool_name: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> bool:
    """Append one event to the per-session dxm JSONL. Best-effort.

    Returns True on successful write, False on any failure (disabled,
    missing session_id, write error). Never raises.
    """
    if os.environ.get("KAIZEN_DXM_DISABLE") == "1":
        return False

    sid = session_id or _discover_sid()
    if not sid:
        return False

    rec: dict[str, Any] = {
        "ts_unix":    time.time(),
        "session_id": sid,
        "evt_type":   evt_type,
    }
    if tool_name:
        rec["tool_name"] = tool_name
    if payload is not None:
        rec["payload"] = payload

    try:
        path = _dxm_dir() / f"events-{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, separators=(",", ":"), default=str) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        return True
    except Exception:
        return False


def emit_subcommand_complete(
    tool: str,
    subcommand: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    session_id: Optional[str] = None,
) -> bool:
    """Convenience: emit '<tool>.<subcommand>.complete' with
    tool_name='kaizen-<tool>'. Single-source the handler-completion
    naming convention so a rename catches all sites and typos in the
    event-name string become impossible by construction.

    Used by handoff (verify/scaffold/create/assess/auto-finalize) and
    intent (match/suggest/scan) handlers.
    """
    return emit_event(
        f"{tool}.{subcommand}.complete",
        tool_name=f"kaizen-{tool}",
        payload=payload,
        session_id=session_id,
    )


__all__ = ["emit_event", "emit_subcommand_complete"]
