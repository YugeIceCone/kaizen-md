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

import datetime as _dt
import hashlib
import os
import subprocess
import sys
import time as _time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "indexers"))

import _index_kit  # noqa: E402 — shared indexer primitives (drift-gated job factory)

# Throttle thresholds (seconds). Tuned per job cost:
#   brain-promote   — 24h  (cheap-ish, but inbox drains don't need to be hourly)
#   brain-evolve    — 24h  (LLM-driven, daily calendar gate handles cadence)
#   gold-promote    —  7d  (durable patterns rarely need re-promotion)
_PROMOTE_THROTTLE_SEC = 86_400
_GOLD_THROTTLE_SEC = 7 * 86_400

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

def _throttled(state: dict, key: str, threshold_sec: int) -> bool:
    """True iff job ``key`` ran within the last ``threshold_sec``."""
    last = (state.get("last_run_at") or {}).get(key, 0)
    return (_time.time() - last) < threshold_sec

def _stamp_last_run(state: dict, key: str) -> None:
    """Mark ``key`` as just-run. Mutates state in place."""
    state.setdefault("last_run_at", {})[key] = _time.time()

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

def _regen_brain_index_subprocess() -> None:
    """Shell out to ``build_index.py index``; raise on non-zero rc so the
    drift-job factory leaves the state hash un-stamped on failure.

    Does NOT pass ``--json`` — build_index.py's ``index`` subparser
    doesn't declare it (the script always prints JSON), so passing it
    triggers argparse rc=2 and silently breaks every daemon tick.
    """
    script = _SCRIPT_DIR / "build_index.py"
    result = subprocess.run(
        [_python(), str(script), "index"],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()[:200] if result.stderr else ""
        raise RuntimeError(f"rc={result.returncode} stderr={stderr}")

# Composed via ``_index_kit.daemon_drift_job`` — preserves the
# ``brain_notes_hash`` state key (not the factory default
# ``brain_index_hash``) so existing daemon state files round-trip.
# Lambdas late-bind ``_brain_notes_hash`` / ``_regen_brain_index_subprocess``
# so test monkey-patches against the module attribute still apply.
run_brain_index = _index_kit.daemon_drift_job(
    action_key="brain-index",
    disable_env="KAIZEN_DAEMON_BRAIN_INDEX_DISABLE",
    hash_fn=lambda: _brain_notes_hash(),
    regen_fn=lambda: _regen_brain_index_subprocess(),
    state_hash_key="brain_notes_hash",
)

def _memory_dir_hash() -> str:
    """Cheap drift signal for the project's auto-memory dir.

    Hashes filename + size + int(mtime) per *.md sibling (excluding
    MEMORY.md itself — the index changes whenever we regen it, would
    cause infinite re-trigger). Returns "" when dir absent.
    """
    sys.path.insert(0, str(_SCRIPT_DIR))
    import better_memory as _bm
    d = _bm._default_memory_dir()
    if not d.is_dir():
        return ""
    h = hashlib.sha256()
    for p in sorted(d.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}\n".encode())
    return h.hexdigest()[:16]

def _regen_memory_sync() -> None:
    """In-process MEMORY.md regen — raises so the drift-job factory
    leaves the state hash un-stamped on failure (next tick retries)."""
    sys.path.insert(0, str(_SCRIPT_DIR))
    import better_memory as _bm
    _bm.regen_index(_bm._default_memory_dir())

# Composed via ``_index_kit.daemon_drift_job`` — preserves the
# ``memory_dir_hash`` state key (not the factory default
# ``memory_sync_hash``) so existing daemon state files round-trip.
# Lambdas late-bind ``_memory_dir_hash`` / ``_regen_memory_sync``
# so test monkey-patches against the module attribute still apply.
run_memory_sync = _index_kit.daemon_drift_job(
    action_key="memory-sync",
    disable_env="KAIZEN_DAEMON_MEMORY_SYNC_DISABLE",
    hash_fn=lambda: _memory_dir_hash(),
    regen_fn=lambda: _regen_memory_sync(),
    state_hash_key="memory_dir_hash",
)

def run_gold_mine(state: dict) -> tuple[bool, str, str]:
    """Weekly trace-mining pass — gold.py mine wraps gold_mine.run_mine.

    Mining parses the trace log, dedupes templates, and emits proposals
    (and auto-captures when score ≥ AUTO_CAPTURE_THRESHOLD). The
    KAIZEN_GOLD_MINE_ENABLE env (read inside run_mine) gates whether
    LLM scoring happens — without it, mining still runs and produces
    unscored proposals.
    """
    action = "gold-mine"
    if _disabled("KAIZEN_DAEMON_GOLD_MINE_DISABLE"):
        return True, "disabled via env", action
    if _throttled(state, action, _GOLD_THROTTLE_SEC):
        return True, "throttled (≤7d since last run)", action
    script = _SCRIPT_DIR / "gold.py"
    result = subprocess.run(
        [_python(), str(script), "mine", "--json"],
        capture_output=True, text=True, timeout=300,
    )
    ok = result.returncode == 0
    if ok:
        _stamp_last_run(state, action)
    msg = f"rc={result.returncode}"
    if not ok and result.stderr:
        msg += f" stderr={result.stderr.strip()[:200]}"
    return ok, msg, action

def run_brain_evolve(state: dict) -> tuple[bool, str, str]:
    """Daily LLM-driven consolidation/reflection (opt-in).

    Default OFF — set ``KAIZEN_DAEMON_BRAIN_EVOLVE_ENABLE=1`` to enable.
    Once enabled, runs at most once per calendar day (tracked via
    ``state["last_evolve_date"]``).
    """
    action = "brain-evolve"
    if os.environ.get("KAIZEN_DAEMON_BRAIN_EVOLVE_ENABLE") != "1":
        return True, "opt-in only (set KAIZEN_DAEMON_BRAIN_EVOLVE_ENABLE=1)", action
    today = _dt.date.today().isoformat()
    if state.get("last_evolve_date") == today:
        return True, f"already ran today ({today})", action
    script = _SCRIPT_DIR / "brain_evolve.py"
    result = subprocess.run(
        [_python(), str(script), "--json"],
        capture_output=True, text=True, timeout=600,
    )
    ok = result.returncode == 0
    if ok:
        state["last_evolve_date"] = today
    msg = f"rc={result.returncode}"
    if not ok and result.stderr:
        msg += f" stderr={result.stderr.strip()[:200]}"
    return ok, msg, action

def run_brain_promote(state: dict) -> tuple[bool, str, str]:
    """Promote aged Inbox drafts → typed Notes (24h throttle).

    Drains the un-promoted draft backlog over time without flooding
    the brain on every tick.
    """
    action = "brain-promote"
    if _disabled("KAIZEN_DAEMON_BRAIN_PROMOTE_DISABLE"):
        return True, "disabled via env", action
    if _throttled(state, action, _PROMOTE_THROTTLE_SEC):
        return True, "throttled (≤24h since last run)", action
    script = _SCRIPT_DIR / "brain_promote.py"
    result = subprocess.run(
        [_python(), str(script), "--apply", "--json"],
        capture_output=True, text=True, timeout=300,
    )
    ok = result.returncode == 0
    if ok:
        _stamp_last_run(state, action)
    msg = f"rc={result.returncode}"
    if not ok and result.stderr:
        msg += f" stderr={result.stderr.strip()[:200]}"
    return ok, msg, action
