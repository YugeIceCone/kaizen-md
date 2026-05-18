"""kaizen daemon — pure-function job registry.

Each ``run_<job>(state)`` returns ``(ok: bool, msg: str, action_key: str)``.

- ``ok`` — True iff the job completed without error. Disabled / throttled
  / no-drift jobs all return True (they're not failures, just skips).
- ``msg`` — short status string for the daemon log.
- ``action_key`` — stable identifier the orchestrator uses to count
  invocations in ``state["actions"]``.

Jobs honor ``KAIZEN_DAEMON_<JOB>_DISABLE=1`` (drift-resilient env read
per call). Throttle policy + state stamping live in daemon.py — these
are pure: pass in state, mutate state, return tuple.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


def _disabled(env_var: str) -> bool:
    return os.environ.get(env_var) == "1"


def _python() -> str:
    return sys.executable or "python3"


def run_brain_audit(state: dict) -> tuple[bool, str, str]:
    """Mine recent activity → write Inbox drafts. Cheap; runs every tick."""
    action = "brain-audit"
    if _disabled("KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE"):
        return True, "disabled via env", action
    script = _SCRIPT_DIR / "brain_audit.py"
    result = subprocess.run(
        [_python(), str(script), "--apply", "--json"],
        capture_output=True, text=True, timeout=120,
    )
    ok = result.returncode == 0
    msg = f"rc={result.returncode}"
    if not ok and result.stderr:
        msg += f" stderr={result.stderr.strip()[:200]}"
    return ok, msg, action
