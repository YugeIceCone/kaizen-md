"""kaizen indexer-kit — shared primitives across the 7 semantic indexes.

Today each indexer (brain / onboard / knowledge / claude-docs / trace /
scrape / loc) reinvents drift detection + daemon-job wrapping + atomic
SQLite open. This module extracts the 3 most-leveraged primitives so
each indexer can opt-in one at a time without rewrite.

## Public surface

- ``compute_corpus_drift(root, glob, exclude_files=None) -> str``
  Filename + size + int(mtime) sha-256[:16] over the matching files.
  Cheap, stat-only, no content read. Same shape as the existing
  ``brain-index`` and ``memory-sync`` daemon-job hashes.

- ``daemon_drift_job(action_key, disable_env, hash_fn, regen_fn,
    state_hash_key=None) -> callable``
  Returns a ``(state) -> (ok, msg, action)`` closure ready to plug
  into ``daemon.py::tick()`` alongside the existing 12 jobs.
  Handles: disable-env early-out, no-drift-skip, regen invocation,
  state-stamp on success, fail-without-stamp on error.

- ``atomic_open_with_migrations(db_path, schema_sql, migrations,
    pragmas=()) -> Connection``
  Thin wrapper over the existing ``_sqlite.open_indexer_db`` that
  ALSO runs a list of migration callbacks (matching the
  ``apply_migrations(conn)`` pattern). Lets indexers without their
  own schema module compose this directly.

Each function is pure-stdlib + small (≤30 LOC). Composes existing
``_sqlite``; doesn't replace it.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, Iterable

# ─── Pure: drift detection ───────────────────────────────────────────

def compute_corpus_drift(root: Path, glob: str = "**/*.md",
                          exclude_files: Iterable[str] | None = None) -> str:
    """Stat-only sha-256[:16] over files matching ``glob`` under ``root``.

    Excludes filenames in ``exclude_files`` (default: empty). Used by
    daemon jobs to skip regen when no source file has changed.

    Returns "" when root doesn't exist (treated as "no corpus", which
    coerces no-drift logic to a "nothing to do" state).
    """
    root = Path(root)
    if not root.is_dir():
        return ""
    skip = set(exclude_files or [])
    h = hashlib.sha256()
    any_file = False
    for p in sorted(root.glob(glob)):
        if p.name in skip:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)}\n".encode())
        any_file = True
    return h.hexdigest()[:16] if any_file else ""

# ─── Adapter: daemon-job factory ────────────────────────────────────

def daemon_drift_job(
    action_key: str,
    disable_env: str,
    hash_fn: Callable[[], str],
    regen_fn: Callable[[], object],
    state_hash_key: str | None = None,
) -> Callable[[dict], tuple[bool, str, str]]:
    """Return a (state) → (ok, msg, action) callable for ``daemon.tick()``.

    The returned closure implements the canonical drift-gated daemon
    job pattern (matches brain-index / memory-sync today):

      1. Honor ``KAIZEN_DAEMON_<X>_DISABLE=1`` via ``disable_env``.
      2. Compute current corpus hash via ``hash_fn()``.
      3. Compare against ``state[state_hash_key]`` (default:
         ``f"{action_key}_hash"``); skip if equal.
      4. Call ``regen_fn()`` on drift. Stamp state on success.
      5. On exception: return (False, error_msg, action) — state NOT
         stamped, so next tick retries.
    """
    key = state_hash_key or f"{action_key.replace('-', '_')}_hash"

    def job(state: dict) -> tuple[bool, str, str]:
        if os.environ.get(disable_env) == "1":
            return True, "disabled via env", action_key
        current = hash_fn()
        prior = state.get(key, "")
        if current and current == prior:
            return True, f"no drift (hash={current})", action_key
        try:
            regen_fn()
        except Exception as e:  # noqa: BLE001
            return False, f"regen failed: {type(e).__name__}: {e}", action_key
        state[key] = current
        msg = f"regen ok (hash {prior or 'none'} → {current})"
        return True, msg, action_key

    return job

# ─── Adapter: SQLite open with migrations ────────────────────────────

def atomic_open_with_migrations(
    db_path: Path,
    schema_sql: str,
    migrations: Iterable[Callable[[sqlite3.Connection], None]] = (),
    pragmas: Iterable[str] = (),
) -> sqlite3.Connection:
    """Open a SQLite db, ensure schema, run idempotent migrations.

    Thin wrapper over ``_sqlite.open_indexer_db`` that adds the
    migration-callbacks pattern used by ``onboard_schema.apply_migrations``.
    Indexers without a dedicated schema module can pass an inline list.

    All migrations must be idempotent (ALTER-if-absent, CREATE IF NOT
    EXISTS); the pattern is described in ``onboard_schema.py`` migration
    helpers.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _sqlite as _kz_sqlite
    conn = _kz_sqlite.open_indexer_db(
        db_path, schema_sql,
        pragmas=tuple(pragmas), create=True,
    )
    for migrate in migrations:
        migrate(conn)
    return conn

__all__ = [
    "compute_corpus_drift",
    "daemon_drift_job",
    "atomic_open_with_migrations",
]
