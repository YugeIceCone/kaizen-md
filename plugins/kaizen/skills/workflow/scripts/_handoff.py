"""kaizen _handoff — core for the handoff feature: paths, config, and
the SQLite handoff store.

Refactored from the recovered `~/.claude/scripts/stores.py` — the lost
handoff DB helper (see the provenance hunt + CHANGELOG 1.36.0). That
module was a 938-line session-logger god-file; this extracts ONLY the
handoff slice — the `handoffs` table + save / latest / list — into the
canonical kaizen feature shape, plugin-owned instead of depending on
an unshipped external script.

Division of labour: the filesystem YAML at
`<handoffs_dir>/<session>/<ts>.yaml` is the SYSTEM OF RECORD —
agent-authored, portable, human-readable. This SQLite store is the
queryable INDEX — fast `latest` / `list`. `save_handoff` upserts on
`file_path`, so re-saving the same handoff (e.g. after Step 4 sets the
final outcome) updates the row instead of duplicating it.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import _sqlite as _kz_sqlite  # noqa: E402  — shared SQLite open/meta helpers

PLUGIN_ROOT = SCRIPT_DIR.parent.parent.parent  # plugins/kaizen
DOMAIN_DIR = PLUGIN_ROOT / "skills" / "handoff" / "domain"

# Mirrors domain/handoff.yaml::status — kept here too so the store can
# coerce defensively without a yaml load on the hot path.
VALID_STATUS = ("partial", "complete", "blocked")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS handoffs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    file_path   TEXT NOT NULL UNIQUE,
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'partial'
);
CREATE INDEX IF NOT EXISTS idx_handoffs_created ON handoffs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_handoffs_session ON handoffs(session_id);
CREATE TABLE IF NOT EXISTS handoff_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Handoffs are durable records — favour durability over write speed.
_PRAGMAS = "PRAGMA journal_mode=WAL;\nPRAGMA synchronous=FULL;\n"


# ─── Path resolution (env-aware, mirrors _brain.brain_root) ──────────


def handoff_db_path() -> Path:
    """SQLite handoff-index path. Env-overridable (KAIZEN_HANDOFF_DB)
    for test sandboxing — mirrors KAIZEN_BRAIN_DB / KAIZEN_KNOWLEDGE_DB."""
    env = os.environ.get("KAIZEN_HANDOFF_DB")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path("~/.claude/.kaizen/handoff.db").expanduser()


def handoffs_dir() -> Path:
    """Root dir for the canonical handoff YAML files — the system of
    record. Env-overridable (KAIZEN_HANDOFF_DIR)."""
    env = os.environ.get("KAIZEN_HANDOFF_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path("~/.claude/thoughts/handoffs").expanduser()


def now_iso() -> str:
    """UTC ISO-8601 timestamp, millisecond precision (matches the
    recovered stores.py::now_iso so existing rows stay comparable)."""
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ─── Store ───────────────────────────────────────────────────────────


def open_db(create: bool = True) -> sqlite3.Connection:
    """Open the handoff index DB via the shared `_sqlite` helper.
    `create=False` skips dir + schema creation (read paths)."""
    return _kz_sqlite.open_indexer_db(
        handoff_db_path(), _SCHEMA_SQL, pragmas=_PRAGMAS, create=create
    )


def save_handoff(
    session_id: str,
    content: str,
    file_path: str,
    *,
    status: str = "partial",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Index a handoff into the store. Upserts on `file_path` — calling
    this again for the same file (e.g. after Step 4 sets the outcome)
    updates the row rather than duplicating it. Returns the row id.

    The YAML file itself is written by the agent (the handoff skill's
    `create` flow); this only indexes it."""
    if not file_path:
        raise ValueError(
            "file_path is required — the YAML file is the handoff's identity"
        )
    if status not in VALID_STATUS:
        status = "partial"
    own = conn is None
    if own:
        conn = open_db(create=True)
    try:
        conn.execute(
            "INSERT INTO handoffs (session_id, created_at, file_path, content, status) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "  session_id = excluded.session_id, "
            "  created_at = excluded.created_at, "
            "  content    = excluded.content, "
            "  status     = excluded.status",
            (session_id, now_iso(), file_path, content, status),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM handoffs WHERE file_path = ?", (file_path,)
        ).fetchone()
        return int(row["id"])
    finally:
        if own:
            conn.close()


def latest_handoffs(
    limit: int = 1, *, conn: Optional[sqlite3.Connection] = None
) -> list[dict]:
    """Most recent handoff(s), newest first — full rows incl. `content`.
    This is what `resume` with no args reads. Returns [] when no store
    exists yet (never raises on a missing/empty DB)."""
    own = conn is None
    if own:
        if not handoff_db_path().exists():
            return []
        conn = open_db(create=False)
    try:
        rows = conn.execute(
            "SELECT id, session_id, created_at, file_path, content, status "
            "FROM handoffs ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if own:
            conn.close()


def list_handoffs(
    limit: int = 20,
    *,
    session_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Recent handoffs, newest first — metadata only (no `content`;
    use `latest_handoffs` for the full YAML). Optionally filtered by
    `session_id`. Returns [] when no store exists yet."""
    own = conn is None
    if own:
        if not handoff_db_path().exists():
            return []
        conn = open_db(create=False)
    try:
        if session_id:
            rows = conn.execute(
                "SELECT id, session_id, created_at, file_path, status FROM handoffs "
                "WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, session_id, created_at, file_path, status FROM handoffs "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if own:
            conn.close()
