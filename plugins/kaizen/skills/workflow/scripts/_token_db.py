#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "tree-sitter>=0.23",
#   "tree-sitter-rust>=0.23",
#   "tree-sitter-python>=0.23",
# ]
# ///
"""Token-map SQLite layer for kaizen-tokens MCP server.

T2 — full schema (files + slots + slots_by_name + indexes), file/slot
CRUD, V1 rename detection (blake3 match against `path_gone=1` rows),
V7/V32 name-stable address table, append-only tombstoning, V25
IMMEDIATE-tx wrapping for version bumps (`with self.conn:`), and
V20 grammar_version column for incremental re-index on grammar upgrade.

Tree-sitter deps live in the PEP-723 header so `uv run --script` can
pre-warm them for downstream consumers (`_token_extractor.py`, watcher,
MCP server). The DB layer itself is stdlib-only (sqlite3 + pathlib).

Private helper (underscore-prefixed) — exempt from
`bin-wrapper-per-cli` iron-law (see `_iron_laws.py:196`).

See spec `docs/2026-05-18-positional-token-schema-design.md` for the
full V-additions context.
"""
from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Optional

__all__ = ["TokenDB", "Slot"]


@dataclasses.dataclass
class Slot:
    """A single addressable token within a file.

    `slot` is the integer index (0 = whole body, 1 = path, ≥2 = AST
    items in source order). `parent` is the V32 parent qualifier
    ("" for top-level; "Foo<T>" / "ClassName" for nested). `body`
    is inlined if < 4 KB; otherwise NULL and fetched from disk via
    byte offsets at read time.
    """

    slot: int
    kind: str              # "body" | "path" | "fn" | "struct" | "comment"
    name: Optional[str]    # NULL for body/path
    parent: str            # "" for top-level (V32 PRIMARY KEY-safe)
    byte_start: int
    byte_end: int
    body: Optional[bytes]  # inlined if < 4 KB else NULL
    content_hash: str      # per-slot blake3/sha256 (ETag)


# V20 grammar_version + V25 IMMEDIATE-tx are honored in the runtime
# methods below; the schema itself only needs to carry the columns.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path             TEXT NOT NULL UNIQUE,
    blake3           TEXT NOT NULL,
    language         TEXT,
    grammar_version  TEXT,
    version          INTEGER DEFAULT 1,
    mtime            INTEGER NOT NULL,
    skipped_reason   TEXT,
    path_gone        INTEGER DEFAULT 0   -- transient flag for rename detection (V1)
);
CREATE INDEX IF NOT EXISTS idx_files_blake3 ON files(blake3);

CREATE TABLE IF NOT EXISTS slots (
    file_id          INTEGER NOT NULL,
    slot             INTEGER NOT NULL,
    kind             TEXT NOT NULL,
    name             TEXT,
    parent_qualifier TEXT,
    byte_start       INTEGER NOT NULL,
    byte_end         INTEGER NOT NULL,
    body             BLOB,
    content_hash     TEXT NOT NULL,
    tombstoned       INTEGER DEFAULT 0,
    PRIMARY KEY (file_id, slot),
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);
CREATE INDEX IF NOT EXISTS idx_slots_kind ON slots(file_id, kind);

CREATE TABLE IF NOT EXISTS slots_by_name (
    file_id          INTEGER NOT NULL,
    kind             TEXT NOT NULL,
    parent_qualifier TEXT NOT NULL DEFAULT '',
    name             TEXT NOT NULL,
    slot             INTEGER NOT NULL,
    PRIMARY KEY (file_id, kind, parent_qualifier, name)
);
"""


class TokenDB:
    """SQLite-backed token map.

    Per spec V25: write paths wrap in `with self.conn:` so SQLite
    issues an IMMEDIATE transaction; readers see fully old or fully
    new state, never torn. Single-writer (the kaizen-watch daemon),
    so the default rollback journal is sufficient — no WAL.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ─── Schema ──────────────────────────────────────────────────────

    def init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA)

    # ─── File CRUD (V1 rename detection lives here) ──────────────────

    def upsert_file(
        self,
        *,
        path: str,
        blake3: str,
        language: Optional[str],
        grammar_version: Optional[str],
        mtime: int,
    ) -> int:
        """Insert or update a file row; return its file_id.

        V1 rename detection: when a new path appears whose blake3
        matches a row already marked `path_gone=1`, reuse that file_id
        (path update + version bump) so the agent's old token addresses
        survive the rename.
        """
        # V1: blake3 match against a tombstoned-path row → rename
        rename_row = self.conn.execute(
            "SELECT file_id FROM files WHERE blake3 = ? AND path_gone = 1 LIMIT 1",
            (blake3,),
        ).fetchone()
        if rename_row:
            fid = rename_row["file_id"]
            with self.conn:
                self.conn.execute(
                    "UPDATE files SET path=?, mtime=?, path_gone=0, "
                    "version=version+1 WHERE file_id=?",
                    (path, mtime, fid),
                )
            return fid

        # Existing path → in-place update + version bump
        row = self.conn.execute(
            "SELECT file_id FROM files WHERE path = ?", (path,),
        ).fetchone()
        if row:
            with self.conn:
                self.conn.execute(
                    "UPDATE files SET blake3=?, language=?, grammar_version=?, "
                    "mtime=?, version=version+1, path_gone=0 WHERE path=?",
                    (blake3, language, grammar_version, mtime, path),
                )
            return row["file_id"]

        # New file → allocate file_id
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO files(path, blake3, language, grammar_version, mtime) "
                "VALUES(?,?,?,?,?)",
                (path, blake3, language, grammar_version, mtime),
            )
        return cur.lastrowid

    def mark_path_gone(self, path: str) -> None:
        """Mark a path as removed without losing its file_id.

        Pre-rename hook: the watcher calls this on a delete event so the
        next-tick upsert can match by blake3 and reuse the file_id.
        """
        with self.conn:
            self.conn.execute(
                "UPDATE files SET path_gone=1 WHERE path=?", (path,),
            )

    # ─── Slot CRUD (V25 IMMEDIATE-tx + V7/V32 name table) ────────────

    def upsert_slots(self, file_id: int, slots: list[Slot]) -> None:
        """Insert or replace a batch of slots atomically.

        Wrapped in `with self.conn:` (V25) so the entire batch lands as
        one IMMEDIATE transaction — readers never see a half-updated
        slot list. Named slots also populate `slots_by_name` for V7/V32
        name-stable addressing.
        """
        with self.conn:  # V25 IMMEDIATE-tx
            for s in slots:
                self.conn.execute(
                    "INSERT OR REPLACE INTO slots(file_id, slot, kind, name, "
                    "parent_qualifier, byte_start, byte_end, body, content_hash, "
                    "tombstoned) VALUES(?,?,?,?,?,?,?,?,?,0)",
                    (file_id, s.slot, s.kind, s.name, s.parent,
                     s.byte_start, s.byte_end, s.body, s.content_hash),
                )
                if s.name:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO slots_by_name"
                        "(file_id, kind, parent_qualifier, name, slot)"
                        " VALUES(?,?,?,?,?)",
                        (file_id, s.kind, s.parent, s.name, s.slot),
                    )

    def get_slot(self, file_id: int, slot: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM slots WHERE file_id=? AND slot=?", (file_id, slot),
        ).fetchone()

    def lookup_by_name(
        self, file_id: int, kind: str, name: str, parent: str = "",
    ) -> Optional[int]:
        """V7/V32 — resolve a name-stable address to its current slot int."""
        row = self.conn.execute(
            "SELECT slot FROM slots_by_name "
            "WHERE file_id=? AND kind=? AND parent_qualifier=? AND name=?",
            (file_id, kind, parent, name),
        ).fetchone()
        return row["slot"] if row else None

    def tombstone_slot(self, file_id: int, slot: int) -> None:
        """Mark a slot as removed without deleting it (append-only)."""
        with self.conn:
            self.conn.execute(
                "UPDATE slots SET tombstoned=1 WHERE file_id=? AND slot=?",
                (file_id, slot),
            )

    # ─── Version bumps (V25 atomic) ──────────────────────────────────

    def bump_file_version(self, file_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE files SET version=version+1 WHERE file_id=?",
                (file_id,),
            )

    def get_file_version(self, file_id: int) -> int:
        row = self.conn.execute(
            "SELECT version FROM files WHERE file_id=?", (file_id,),
        ).fetchone()
        return row["version"] if row else 0


if __name__ == "__main__":
    # Phase 1 probe — confirms PEP-723 venv has the 3 deps.
    import tree_sitter        # noqa: F401
    import tree_sitter_rust   # noqa: F401
    import tree_sitter_python # noqa: F401
    print("_token_db.py: deps OK")
