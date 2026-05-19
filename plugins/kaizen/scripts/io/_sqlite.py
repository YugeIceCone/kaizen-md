"""Shared SQLite indexer base (M1 — extract common open_db / meta helpers).

Five indexers — knowledge, claude_docs, trace, scrape, onboard — each used
to redefine `open_db()`, `set_meta()`, `get_meta()` with the same shape.
Only the inline `CREATE TABLE` schema and (for onboard) the performance
pragmas vary. This module collapses the duplicated wrapper while keeping
each indexer's schema string + meta-table name as the per-file knob.

Usage shape (per indexer):

    import _sqlite

    SCHEMA_SQL = '''
        CREATE TABLE IF NOT EXISTS <items_table> ( ... );
        CREATE TABLE IF NOT EXISTS <meta_table> (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    '''

    def open_db(create: bool = True) -> sqlite3.Connection:
        return _sqlite.open_indexer_db(DB_PATH, SCHEMA_SQL, create=create)

    set_meta = lambda c, k, v: _sqlite.set_meta(c, "<meta_table>", k, v)
    get_meta = lambda c, k, d="": _sqlite.get_meta(c, "<meta_table>", k, d)

onboard passes `pragmas=...` so its PRAGMAs (WAL, synchronous=NORMAL,
cache_size, mmap_size, temp_store=MEMORY, foreign_keys=ON) run on every
open — the other four indexers pass an empty string.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def open_indexer_db(
    db_path: Path,
    schema_sql: str,
    *,
    pragmas: str = "",
    create: bool = True,
) -> sqlite3.Connection:
    """Open SQLite at `db_path`, set row_factory=Row, run optional pragmas
    and schema.

    `create=True` (default) creates parent dirs + executes `schema_sql`
    (idempotent via `CREATE TABLE IF NOT EXISTS`). `create=False` skips
    both — used by read-only paths like search/stats.

    `pragmas` is an executescript block applied to every open (matches
    onboard's behavior where WAL etc. apply for both read + write).
    Pass an empty string for stock behavior.
    """
    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    if pragmas:
        conn.executescript(pragmas)
    if create and schema_sql:
        conn.executescript(schema_sql)
    return conn


def set_meta(conn: sqlite3.Connection, table: str, key: str, value: str) -> None:
    """INSERT OR REPLACE into `<table>(key, value)`."""
    conn.execute(
        f"INSERT OR REPLACE INTO {table} (key, value) VALUES (?, ?)",
        (key, value),
    )


def get_meta(
    conn: sqlite3.Connection,
    table: str,
    key: str,
    default: str = "",
) -> str:
    """SELECT value FROM `<table>` WHERE key = ?; return default on miss."""
    row = conn.execute(
        f"SELECT value FROM {table} WHERE key = ?", (key,),
    ).fetchone()
    return row["value"] if row else default
