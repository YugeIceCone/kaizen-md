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

import hashlib
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


def _brain_notes_dir() -> Path:
    env = os.environ.get("KAIZEN_BRAIN_PATH")
    base = Path(env) if env else Path.home() / ".claude" / ".kaizen" / "brain"
    return base / "Notes"


def _brain_notes_hash() -> str:
    """Cheap drift signal — hash filename + size + integer mtime per Note.

    Skips file contents (rglob+stat is microseconds; reading every Note
    would be IO-bound). Returns "" when Notes/ is absent so an empty
    brain doesn't repeatedly trigger reindex.
    """
    d = _brain_notes_dir()
    if not d.is_dir():
        return ""
    h = hashlib.sha256()
    for p in sorted(d.rglob("*.md")):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}\n".encode())
    return h.hexdigest()[:16]


def run_brain_index(state: dict) -> tuple[bool, str, str]:
    """(Re)build brain.db when Notes/ has drifted since last tick.

    State carries ``brain_notes_hash``. On successful reindex, the new
    hash is stamped — failure leaves the old hash so next tick retries.
    """
    action = "brain-index"
    if _disabled("KAIZEN_DAEMON_BRAIN_INDEX_DISABLE"):
        return True, "disabled via env", action
    current = _brain_notes_hash()
    prior = state.get("brain_notes_hash", "")
    if current and current == prior:
        return True, f"no drift (hash={current})", action
    script = _SCRIPT_DIR / "brain_index.py"
    result = subprocess.run(
        [_python(), str(script), "index", "--json"],
        capture_output=True, text=True, timeout=300,
    )
    ok = result.returncode == 0
    if ok:
        state["brain_notes_hash"] = current
    msg = f"reindex ({prior or 'none'} → {current}) rc={result.returncode}"
    if not ok and result.stderr:
        msg += f" stderr={result.stderr.strip()[:200]}"
    return ok, msg, action
