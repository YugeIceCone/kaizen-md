"""kaizen onboard-index — SQLite schema + migrations.

Carved out of `onboard_index.py` so that file keeps only the indexing
orchestration + per-indexer knobs. This module owns:

  - `SCHEMA_SQL` — the `CREATE TABLE IF NOT EXISTS` DDL for a fresh db.
  - the four idempotent migration helpers that bring a pre-existing db
    up to the current column/table tier (ALTER-if-absent + index).
  - `apply_migrations(conn)` — runs the migrations in dependency order.

`open_db()` in onboard_index.py is the sole consumer: it executes
`SCHEMA_SQL` for fresh dbs, then calls `apply_migrations(conn)`.
"""

import sqlite3

SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS code_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL UNIQUE,
        language TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        sloc INTEGER NOT NULL,
        snippet TEXT NOT NULL,
        embedding BLOB NOT NULL,
        sha TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_code_lang ON code_files(language);
    CREATE INDEX IF NOT EXISTS idx_code_path ON code_files(path);
    -- v1.31.0+: lossless capture layer. One row per source file
    -- (including failures: `error IS NOT NULL`, `text IS NULL`).
    -- do_dump writes here; do_filter reads here. Re-running the
    -- clean/chunk/embed stage does NOT re-read the filesystem
    -- — it reads this table. Errors surface as queryable rows
    -- instead of a counter.
    CREATE TABLE IF NOT EXISTS code_files_raw (
        path TEXT PRIMARY KEY,
        sha TEXT,
        language TEXT,
        bytes INTEGER,
        sloc_raw INTEGER,
        mtime TEXT,
        text TEXT,
        error TEXT,
        captured_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_raw_error ON code_files_raw(error);
    CREATE TABLE IF NOT EXISTS code_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    -- v1.28.0+: chunk-level table for RAG-grade hybrid search.
    -- One file → many chunks. Each chunk carries its own embedding
    -- and a (char_start, char_end) back to the source for citation.
    -- language is denormalized so hybrid_search can filter without
    -- joining to code_files.
    CREATE TABLE IF NOT EXISTS code_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
        chunk_idx INTEGER NOT NULL,
        char_start INTEGER NOT NULL,
        char_end INTEGER NOT NULL,
        text TEXT NOT NULL,
        embedding BLOB NOT NULL,
        embedding_q8 BLOB,
        language TEXT NOT NULL,
        -- O1 (v1.32): 'code' for cleaned-source chunks (default),
        -- 'doc' for extracted-docstring chunks. Sidecar signal for
        -- "why does X exist" queries.
        kind TEXT NOT NULL DEFAULT 'code',
        -- O2 (v1.33): enclosing symbol name when ast-chunked (Python).
        -- Empty string for non-ast paths. Populated by _ast_chunk's
        -- chunk_python_by_symbol when language='python'.
        symbol_name TEXT NOT NULL DEFAULT '',
        -- E9 (v1.34): SPLADE sparse-embedding sidecar — JSON-encoded
        -- {token_id: weight}. NULL when KAIZEN_SPARSE_ENABLE is off or
        -- transformers/torch unavailable. _sparse.deserialize decodes it
        -- at search time; sparse_search in _search.py fuses with dense.
        embedding_sparse BLOB,
        -- v1.40 (symbol-search Phase 2): 1-indexed inclusive line range
        -- populated from _ast_chunk.SymbolChunk for Python; 0 for
        -- sliding-window non-AST chunks. Enables symbol_search_mcp
        -- to return exact (file, line_start, line_end) for matches so
        -- the agent can Read just the slice.
        line_start INTEGER NOT NULL DEFAULT 0,
        line_end INTEGER NOT NULL DEFAULT 0,
        UNIQUE(file_id, chunk_idx)
    );
    CREATE INDEX IF NOT EXISTS idx_chunk_file ON code_chunks(file_id);
    CREATE INDEX IF NOT EXISTS idx_chunk_lang ON code_chunks(language);
    -- idx_chunk_kind + idx_chunk_symbol are created inside their migration
    -- helpers so they work on fresh AND pre-existing dbs (the ALTER must
    -- run before the CREATE INDEX on those columns).

    -- O6 (v1.33): xref table for symbol-level cross-references. Each row
    -- ties one chunk to one symbol it imports / defines / calls. Enables
    -- "find chunks that import X" / "who calls Y" queries via M7's
    -- onboard_xref MCP tool.
    CREATE TABLE IF NOT EXISTS code_chunks_xref (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chunk_id INTEGER NOT NULL REFERENCES code_chunks(id) ON DELETE CASCADE,
        symbol TEXT NOT NULL,
        kind TEXT NOT NULL,  -- 'import' | 'def' | 'call'
        UNIQUE(chunk_id, symbol, kind)
    );
    CREATE INDEX IF NOT EXISTS idx_xref_chunk ON code_chunks_xref(chunk_id);
    CREATE INDEX IF NOT EXISTS idx_xref_symbol ON code_chunks_xref(symbol);
    CREATE INDEX IF NOT EXISTS idx_xref_kind ON code_chunks_xref(kind);

    -- E10 (v1.34): ColBERT late-interaction sidecar. One row per chunk
    -- carrying a (seq_len, dim) float32 matrix of token-level vectors.
    -- Stored separately because the storage cost is ~10x dense; the
    -- sidecar lets users `DROP TABLE code_chunks_colbert` to reclaim
    -- space without touching code_chunks. Populated only when
    -- KAIZEN_COLBERT_ENABLE=1 + transformers/torch available.
    CREATE TABLE IF NOT EXISTS code_chunks_colbert (
        chunk_id INTEGER PRIMARY KEY REFERENCES code_chunks(id) ON DELETE CASCADE,
        vectors BLOB NOT NULL,   -- packed: <II header + float32 body
        seq_len INTEGER NOT NULL,
        dim     INTEGER NOT NULL
    );
"""


def _migrate_kind_column(conn: sqlite3.Connection) -> None:
    """O1 migration — add `kind` column + index on code_chunks.

    `CREATE TABLE IF NOT EXISTS` won't add columns to an existing table,
    and the schema-level `CREATE INDEX idx_chunk_kind` can't run on a
    pre-v1.32 table that lacks the column. Both happen here.

    Idempotent: ALTER is gated on a PRAGMA probe; index uses
    IF NOT EXISTS. Existing rows get the default 'code' value; new
    doc-chunks land as 'doc'."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
    if "kind" not in cols:
        conn.execute(
            "ALTER TABLE code_chunks ADD COLUMN kind TEXT NOT NULL DEFAULT 'code'"
        )
    # Always ensure the index — works on both freshly-created and migrated dbs.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_kind ON code_chunks(kind)"
    )


def _migrate_symbol_name_column(conn: sqlite3.Connection) -> None:
    """O2 migration — add `symbol_name` column + index on code_chunks.

    Same pattern as _migrate_kind_column. Pre-v1.33 dbs get the column
    via ALTER TABLE; fresh dbs already have it from the schema. The
    CREATE INDEX runs always to handle both code paths."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
    if "symbol_name" not in cols:
        conn.execute(
            "ALTER TABLE code_chunks ADD COLUMN "
            "symbol_name TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_symbol ON code_chunks(symbol_name)"
    )


def _migrate_embedding_sparse_column(conn: sqlite3.Connection) -> None:
    """E9 migration — add `embedding_sparse` BLOB column on code_chunks.

    Mirrors the _migrate_kind_column / _migrate_symbol_name_column
    shape: PRAGMA-probe, ALTER if absent. NULL is the default for
    pre-v1.34 rows; population is gated on KAIZEN_SPARSE_ENABLE so
    existing indexes stay untouched until the user opts in + reindexes.
    No index — sparse vectors are looked up by chunk_id (already the
    PK on code_chunks), so the existing idx_chunk_file is enough."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
    if "embedding_sparse" not in cols:
        conn.execute(
            "ALTER TABLE code_chunks ADD COLUMN embedding_sparse BLOB"
        )


def _migrate_line_columns(conn: sqlite3.Connection) -> None:
    """Phase 2 (symbol-search arc) — add line_start + line_end to
    code_chunks. Populated at index time from _ast_chunk.SymbolChunk
    for Python; non-AST chunks default to 0 (unknown).

    Same PRAGMA-probe + ALTER-if-absent pattern as the prior
    migrations. Pre-existing rows get 0/0; the next reindex of a
    Python file populates real ranges from ast.AST.lineno/end_lineno.

    Enables: symbol_search_mcp returning exact file:line_start-line_end
    so the agent can Read(file, offset, limit) for just the matched
    symbol — no whole-file reads.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
    if "line_start" not in cols:
        conn.execute(
            "ALTER TABLE code_chunks ADD COLUMN line_start INTEGER NOT NULL DEFAULT 0"
        )
    if "line_end" not in cols:
        conn.execute(
            "ALTER TABLE code_chunks ADD COLUMN line_end INTEGER NOT NULL DEFAULT 0"
        )
    # Index on line_start enables symbol_at_line lookups (find symbol
    # enclosing a given line via file_id + line_start <= L <= line_end).
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_line ON code_chunks(file_id, line_start)"
    )


def _migrate_colbert_sidecar(conn: sqlite3.Connection) -> None:
    """E10 migration — ensure the `code_chunks_colbert` sidecar table
    exists. Idempotent — CREATE TABLE IF NOT EXISTS in the schema SQL
    already handles fresh dbs; this runs for pre-v1.34 dbs whose
    schema script didn't include the sidecar."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS code_chunks_colbert (
            chunk_id INTEGER PRIMARY KEY REFERENCES code_chunks(id) ON DELETE CASCADE,
            vectors BLOB NOT NULL,
            seq_len INTEGER NOT NULL,
            dim     INTEGER NOT NULL
        )
        """
    )


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Run the idempotent migrations in order — brings older dbs up to
    the current schema tier. Safe to call on a freshly-created db (every
    step is ALTER-if-absent / CREATE IF NOT EXISTS)."""
    _migrate_kind_column(conn)          # v1.32 — adds `kind`
    _migrate_symbol_name_column(conn)   # v1.33 — adds `symbol_name`
    _migrate_embedding_sparse_column(conn)  # v1.34 — adds `embedding_sparse` (E9)
    _migrate_colbert_sidecar(conn)      # v1.34 — adds code_chunks_colbert (E10)
    _migrate_line_columns(conn)         # v1.40 — adds line_start + line_end (Phase 2)
