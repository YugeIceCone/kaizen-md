"""kaizen hybrid search — BM25 (FTS5) + dense cosine fusion (v1.27.0+).

Ported from Onyx's `_embed_and_hybrid_search` in
`backend/onyx/context/search/retrieval/search_runner.py`. We do the
fusion client-side (Python) because SQLite doesn't have a Vespa-style
rank profile. The math is the same: linear blend of min-max-normalized
BM25 + cosine scores, weighted by `alpha`.

Onyx also retired cross-encoder reranking explicitly — see
`backend/alembic/versions/78ebc66946a0_remove_reranking_from_search_settings.py`.
We don't ship it either. If you need post-retrieval refinement, pipe
top-K through an LLM filter (cheaper, often better).

## Schema contract

Each searchable table (`onboard_chunks`, `knowledge_chunks`, etc.) must
have:

    CREATE TABLE <name> (
        id INTEGER PRIMARY KEY,
        text TEXT NOT NULL,
        embedding BLOB,
        ... (caller's metadata columns)
    );

    CREATE VIRTUAL TABLE <name>_fts USING fts5(
        text,
        content='<name>',
        content_rowid='id'
    );

Plus a sync trigger that mirrors `text` from base → fts. See
`ensure_fts_mirror()` below for the canonical setup.

## RRF for query expansion

`reciprocal_rank_fusion()` is provided for when the caller runs the
same retrieval against multiple query variants (LLM-rephrasings,
keyword-strips, etc.) and wants to merge the ranked lists. Onyx uses
this with `k=50` weights `[1.3, 1.0, 0.7, 0.5]` for
`[semantic, keyword, low-confidence-rephrase, …]`.
"""

from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _embed  # noqa: E402


# ─── FTS5 setup ───────────────────────────────────────────────────────


def ensure_fts_mirror(conn: sqlite3.Connection, base_table: str) -> None:
    """Create `<base_table>_fts` virtual table + sync triggers if absent.

    Pattern: contentless FTS5 with `content=` pointing back at the base
    table, so storage isn't duplicated. Triggers keep `_fts` in sync on
    insert / update / delete of the base row.
    """
    fts = f"{base_table}_fts"
    cur = conn.cursor()
    # Check whether the FTS table already exists.
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (fts,),
    ).fetchone()
    if row is not None:
        return

    # v1.31.0+ tokenizer tune: `porter unicode61 remove_diacritics 2`
    # — porter stemming so `embed`/`embedding`/`embedded` collide,
    # unicode61 strips diacritics for naive query robustness. The
    # `tokenchars '_-'` keeps identifier-shaped tokens (e.g.
    # `code_chunks`, `do-search`) intact instead of splitting on the
    # separator. Identifier-friendly behavior is what we want for
    # code search; the default fts5 tokenizer would shred those.
    cur.executescript(f"""
        CREATE VIRTUAL TABLE {fts} USING fts5(
            text,
            content='{base_table}',
            content_rowid='id',
            tokenize="porter unicode61 remove_diacritics 2 tokenchars '_-'"
        );

        CREATE TRIGGER {base_table}_ai AFTER INSERT ON {base_table} BEGIN
            INSERT INTO {fts}(rowid, text) VALUES (new.id, new.text);
        END;

        CREATE TRIGGER {base_table}_ad AFTER DELETE ON {base_table} BEGIN
            INSERT INTO {fts}({fts}, rowid, text) VALUES ('delete', old.id, old.text);
        END;

        CREATE TRIGGER {base_table}_au AFTER UPDATE ON {base_table} BEGIN
            INSERT INTO {fts}({fts}, rowid, text) VALUES ('delete', old.id, old.text);
            INSERT INTO {fts}(rowid, text) VALUES (new.id, new.text);
        END;
    """)
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection, base_table: str) -> None:
    """Force-rebuild the FTS mirror from the base table contents.

    Useful after bulk imports that bypassed the triggers, or to recover
    from a corrupt FTS state."""
    fts = f"{base_table}_fts"
    conn.execute(f"INSERT INTO {fts}({fts}) VALUES('rebuild')")
    conn.commit()


# ─── BM25 retrieval ──────────────────────────────────────────────────


def _fts5_safe(query: str) -> str:
    """Wrap each whitespace-separated token in double quotes so FTS5
    treats it as a literal phrase. Drops tokens that are empty or pure
    punctuation. Without this, queries like 'foo:bar' or 'a-b' break the
    FTS5 parser."""
    tokens = []
    for tok in query.split():
        # Strip outer quotes if user already provided them.
        cleaned = tok.strip('"\'')
        # FTS5 chokes on bare punctuation tokens; keep only alnum-bearing.
        if not any(c.isalnum() for c in cleaned):
            continue
        # Escape internal double quotes.
        cleaned = cleaned.replace('"', '""')
        tokens.append(f'"{cleaned}"')
    return " OR ".join(tokens) if tokens else '""'


def bm25_search(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 50,
) -> list[tuple[int, float]]:
    """Run a BM25 search via FTS5. Returns [(rowid, -bm25_score), ...]
    sorted by relevance (best first). Returns negated score because
    SQLite's bm25() is more-negative = better; we flip to more-positive
    = better for consistency with cosine."""
    fts = f"{base_table}_fts"
    safe = _fts5_safe(query)
    rows = conn.execute(
        f"""SELECT rowid, bm25({fts}) AS score
            FROM {fts}
            WHERE {fts} MATCH ?
            ORDER BY score
            LIMIT ?""",
        (safe, top_k),
    ).fetchall()
    # SQLite bm25 returns NEGATIVE values (lower = better). Flip sign.
    return [(int(r[0]), -float(r[1])) for r in rows]


# ─── Dense retrieval ─────────────────────────────────────────────────


def dense_search(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 50,
    *,
    extra_where: str = "",
    extra_params: Sequence = (),
    apply_prefix: bool = True,
) -> list[tuple[int, float]]:
    """Cosine similarity against `<base_table>.embedding`. Returns
    [(rowid, cosine_score), ...] sorted best-first.

    v1.31.0+: vectorized via a single numpy matmul over an (N, D)
    stacked matrix instead of a Python loop over rows. At shodan-scale
    (~3000 chunks, 384 dim) this is roughly 50-100× faster per query.

    Rows whose embedding dim doesn't match the query are filtered out
    with a stderr warning — matches the legacy behavior for partial
    re-embedding after a backend swap."""
    import _chunk  # local import — avoid circular if _chunk grows
    np = _embed.require_numpy()
    q = _chunk.apply_query_prefix(query) if apply_prefix else query
    qblob, _ = _embed.embed_one(q)
    qvec = np.frombuffer(qblob, dtype=np.float32)
    q_dim = int(qvec.shape[0])
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)

    where = f" WHERE embedding IS NOT NULL{(' AND ' + extra_where) if extra_where else ''}"
    rows = conn.execute(
        f"SELECT id, embedding FROM {base_table}{where}",
        list(extra_params),
    ).fetchall()
    if not rows:
        return []

    # Stack embeddings into one (N, D) matrix. Frame the dim-mismatch
    # filter as a single pass over the python list (cheap; the matmul
    # dominates cost).
    ids: list[int] = []
    vecs: list[np.ndarray] = []
    skipped = 0
    for r in rows:
        v = np.frombuffer(r[1], dtype=np.float32)
        if v.shape[0] != q_dim:
            skipped += 1
            continue
        ids.append(int(r[0]))
        vecs.append(v)
    if not vecs:
        if skipped:
            _warn_dim_skip(skipped, q_dim)
        return []
    mat = np.stack(vecs)                          # (N, D)
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
    mat_n = mat / norms                            # (N, D) row-normalized
    scores = mat_n @ qnorm                         # (N,) cosine = dot(unit, unit)
    if skipped:
        _warn_dim_skip(skipped, q_dim)
    # argsort descending; partial-sort would be O(N + K log K) but
    # numpy's full sort is plenty fast at our scale and keeps the code
    # simple.
    order = np.argsort(-scores)[:top_k]
    return [(ids[i], float(scores[i])) for i in order]


def _warn_dim_skip(skipped: int, q_dim: int) -> None:
    sys.stderr.write(
        f"kaizen search: skipped {skipped} row(s) with dim != {q_dim} — "
        "reindex after embed-backend change\n"
    )


# ─── Whole-row cosine (M6 — shared by knowledge / claude_docs / scrape /
#     trace; onboard uses the chunked hybrid_search path above) ────────


def cosine_topk(
    conn: sqlite3.Connection,
    table: str,
    query: str,
    *,
    top_k: int = 10,
    embedding_col: str = "embedding",
    select_cols: str = "*",
    where: str = "",
    params: Sequence = (),
    apply_query_prefix: bool = False,
) -> list[tuple[sqlite3.Row, float]]:
    """Whole-row cosine ranking. Returns (row, score) pairs sorted desc.

    Designed for the 4 simpler indexers (knowledge / claude_docs / scrape
    / trace) that each had a near-identical "embed query → fetch all rows
    → cosine → top-k" loop in their `do_search()`. Onboard is **not** a
    caller — it uses the chunked `hybrid_search` path.

    - Embeds `query` via `_embed.embed_one()`.
    - Optionally prepends the asymmetric `search_query: ` prefix
      (`apply_query_prefix=True`, knowledge-style). For
      `search_document: ` (claude_docs-style) the caller pre-applies
      `_chunk.apply_passage_prefix` before passing — keeps this helper
      one-knob.
    - `select_cols` defaults to `*` so callers can name their own
      columns in the returned `sqlite3.Row`. `embedding_col` says which
      column holds the float32 blob.
    - Optional `WHERE` clause + params for SQL pre-filters (trace_index
      uses src/sid/evt/since).
    - Filters out rows whose embedding dim != query dim, with the
      stderr warning + count surfaced via `_warn_dim_skip`.
    """
    np = _embed.require_numpy()
    if apply_query_prefix:
        import _chunk  # local import — same pattern as dense_search
        q = _chunk.apply_query_prefix(query)
    else:
        q = query
    qblob, _ = _embed.embed_one(q)
    qvec = np.frombuffer(qblob, dtype=np.float32)
    q_dim = int(qvec.shape[0])
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)

    where_clause = f" WHERE {where}" if where else ""
    sql = f"SELECT {select_cols} FROM {table}{where_clause}"
    rows = conn.execute(sql, list(params)).fetchall()
    if not rows:
        return []

    kept_rows: list[sqlite3.Row] = []
    vecs = []
    skipped = 0
    for r in rows:
        blob = r[embedding_col]
        if not blob:
            continue
        v = np.frombuffer(blob, dtype=np.float32)
        if v.shape[0] != q_dim:
            skipped += 1
            continue
        kept_rows.append(r)
        vecs.append(v)
    if skipped:
        _warn_dim_skip(skipped, q_dim)
    if not vecs:
        return []

    mat = np.stack(vecs)                                # (N, D)
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
    mat_n = mat / norms                                  # (N, D) row-normalized
    scores = mat_n @ qnorm                               # (N,) cosine
    order = np.argsort(-scores)[:top_k]
    return [(kept_rows[i], float(scores[i])) for i in order]


def try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Best-effort load of the sqlite-vec extension. Returns True on
    success, False otherwise.

    Two failure modes the caller should expect:
      1. sqlite-vec wheel not installed (ImportError) — bare python3 path.
      2. SQLite built without `enable_load_extension` (some distros).

    On either, the caller falls back to the in-Python matmul path."""
    try:
        import sqlite_vec  # type: ignore
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (sqlite3.OperationalError, AttributeError):
        return False
    return True


def ensure_vec_table(conn: sqlite3.Connection, base_table: str, dim: int) -> bool:
    """Create the sqlite-vec virtual table mirror for `base_table` if absent.

    Schema: `vec_<base_table>(id INTEGER PRIMARY KEY, embedding float[D])`.
    Populated lazily on first call; subsequent calls top up new rows.
    Returns True if the table is ready (created + populated), False if
    sqlite-vec is unavailable."""
    if not try_load_sqlite_vec(conn):
        return False
    vec_table = f"vec_{base_table}"
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table} USING vec0("
            f"id INTEGER PRIMARY KEY, embedding float[{dim}])"
        )
    except sqlite3.OperationalError as e:
        sys.stderr.write(f"kaizen vec: vec0 table create failed: {e}\n")
        return False
    # Top up rows that are in the base table but missing from vec.
    missing = conn.execute(
        f"SELECT b.id, b.embedding FROM {base_table} b "
        f"LEFT JOIN {vec_table} v ON v.id = b.id "
        f"WHERE v.id IS NULL AND b.embedding IS NOT NULL"
    ).fetchall()
    for r in missing:
        try:
            conn.execute(
                f"INSERT INTO {vec_table}(id, embedding) VALUES (?, ?)",
                (int(r[0]), bytes(r[1])),
            )
        except sqlite3.OperationalError:
            # dim mismatch or similar — skip the row, search will hit
            # the base table for it via the fallback path.
            continue
    conn.commit()
    return True


def dense_search_vec(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 50,
    *,
    apply_prefix: bool = True,
) -> list[tuple[int, float]] | None:
    """v1.31.0+ — sqlite-vec KNN path.

    Returns None when sqlite-vec isn't available or the vec mirror
    table couldn't be populated; the caller then falls back to
    `dense_search` (vectorized matmul).

    sqlite-vec returns Euclidean distance by default; we convert to
    cosine similarity = 1 - (distance² / 2) for normalized vectors
    (sqlite-vec stores unit-norm vectors by convention when called via
    vec0). Since our embeddings aren't pre-normalized, the conversion
    is approximate — use this path when corpus is large enough that
    KNN beats full scan."""
    import _chunk
    np = _embed.require_numpy()
    # Probe + populate the vec mirror.
    cur = conn.cursor()
    # First, learn the dim from the base table's stored embedding.
    row = cur.execute(
        f"SELECT embedding FROM {base_table} WHERE embedding IS NOT NULL LIMIT 1"
    ).fetchone()
    if not row:
        return None
    dim = len(bytes(row[0])) // 4  # float32 = 4 bytes per element
    if not ensure_vec_table(conn, base_table, dim):
        return None

    q = _chunk.apply_query_prefix(query) if apply_prefix else query
    qblob, _ = _embed.embed_one(q)
    qvec = np.frombuffer(qblob, dtype=np.float32)
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)
    qbytes = qnorm.astype(np.float32).tobytes()
    vec_table = f"vec_{base_table}"
    try:
        rows = cur.execute(
            f"SELECT id, distance FROM {vec_table} "
            f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (qbytes, top_k),
        ).fetchall()
    except sqlite3.OperationalError as e:
        sys.stderr.write(f"kaizen vec: knn query failed ({e}); falling back\n")
        return None
    # Convert L2 distance to a cosine-similarity-ish score in [0, 1].
    # Assuming both vectors are unit-norm, L2² = 2 - 2*cos, so
    # cos = 1 - L2²/2. Clip to handle numerical noise.
    return [
        (int(r[0]), max(0.0, min(1.0, 1.0 - (float(r[1]) ** 2) / 2.0)))
        for r in rows
    ]


def dense_search_q8(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 50,
    *,
    extra_where: str = "",
    extra_params: Sequence = (),
    apply_prefix: bool = True,
) -> list[tuple[int, float]]:
    """v1.31.0+ — int8-quantized cosine path.

    Same shape as `dense_search` but reads `embedding_q8` (int8 + 4-byte
    scale) instead of `embedding` (float32). Dequantizes via
    `_quant.dequantize_batch` then one matmul, exactly like the float32
    path. 4× less storage I/O; recall preserved within ~0.01 cosine.

    Falls back to `dense_search` (float32) when the column is missing or
    no rows have been quantized yet."""
    # Probe schema: column exists?
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({base_table})")}
    if "embedding_q8" not in cols:
        return dense_search(
            conn, base_table, query, top_k,
            extra_where=extra_where, extra_params=extra_params,
            apply_prefix=apply_prefix,
        )

    import _chunk, _quant
    np = _embed.require_numpy()
    q = _chunk.apply_query_prefix(query) if apply_prefix else query
    qblob, _ = _embed.embed_one(q)
    qvec = np.frombuffer(qblob, dtype=np.float32)
    q_dim = int(qvec.shape[0])
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)

    expected_bytes = _quant.quant_size(q_dim)
    where = (
        f" WHERE embedding_q8 IS NOT NULL "
        f"AND length(embedding_q8) = {expected_bytes}"
        + (f" AND {extra_where}" if extra_where else "")
    )
    rows = conn.execute(
        f"SELECT id, embedding_q8 FROM {base_table}{where}",
        list(extra_params),
    ).fetchall()
    if not rows:
        # Quantized rows absent — fall back so search keeps working
        # on partially-migrated dbs.
        return dense_search(
            conn, base_table, query, top_k,
            extra_where=extra_where, extra_params=extra_params,
            apply_prefix=apply_prefix,
        )

    ids = [int(r[0]) for r in rows]
    blobs = [bytes(r[1]) for r in rows]
    mat = _quant.dequantize_batch(blobs, q_dim)            # (N, D) float32
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
    mat_n = mat / norms
    scores = mat_n @ qnorm
    order = np.argsort(-scores)[:top_k]
    return [(ids[i], float(scores[i])) for i in order]


# ─── Sparse retrieval (E9 — SPLADE) ──────────────────────────────────
#
# Sparse vectors are stored as JSON {token_id: weight} in the
# `embedding_sparse` BLOB column (populated when KAIZEN_SPARSE_ENABLE=1
# during indexing). The search path:
#
#   1. Encode the query via the same SPLADE model used at index time.
#   2. SELECT all non-NULL `embedding_sparse` rows.
#   3. Compute dot product per row (sparse · sparse).
#   4. Return top-K by descending score.
#
# Falls back to an empty list (NOT to dense_search) when sparse is
# unavailable or the column is empty — the caller (hybrid_search) folds
# sparse in via RRF when results are present and skips it otherwise.


def sparse_search(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 50,
    *,
    extra_where: str = "",
    extra_params: Sequence = (),
) -> list[tuple[int, float]]:
    """v1.34.0+ (E9) — SPLADE sparse-vector cosine via dot product.

    Returns ``[(rowid, sparse_dot_score), ...]`` top-K descending.
    Returns ``[]`` (not a fallback) when:

      - ``embedding_sparse`` column is absent (pre-v1.34 db), OR
      - transformers/torch unavailable (``_sparse.is_available()`` False), OR
      - No rows have a populated sparse vector yet.

    Empty return is intentional: ``hybrid_search`` checks the result
    and skips the sparse term in its RRF when sparse hasn't been
    indexed, so partially-migrated dbs degrade gracefully to BM25 +
    dense."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({base_table})")}
    if "embedding_sparse" not in cols:
        return []
    import _sparse  # local import — heavy deps lazy-loaded only when called
    if not _sparse.is_available():
        return []
    q_sparse = _sparse.encode_sparse(query)
    if not q_sparse:
        return []

    where = (
        " WHERE embedding_sparse IS NOT NULL"
        + (f" AND {extra_where}" if extra_where else "")
    )
    rows = conn.execute(
        f"SELECT id, embedding_sparse FROM {base_table}{where}",
        list(extra_params),
    ).fetchall()
    if not rows:
        return []

    scored: list[tuple[int, float]] = []
    for r in rows:
        d_sparse = _sparse.deserialize(bytes(r[1]))
        score = _sparse.dot_product(q_sparse, d_sparse)
        if score > 0:
            scored.append((int(r[0]), score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ─── ColBERT late-interaction (E10) ──────────────────────────────────
#
# Token-level multi-vector retrieval. Each chunk in the
# `code_chunks_colbert` sidecar has a (seq_len, dim) matrix; the query
# is encoded the same way and MaxSim aggregates per-token cosines into
# a score. Higher storage cost (~10x dense) but better long-tail recall.
#
# Returns [] when the sidecar table is absent or empty — hybrid_search
# does not auto-fold ColBERT; callers opt in explicitly via the
# `colbert_search` MCP tool or by composing in RRF.


def colbert_search(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 50,
    *,
    sidecar_table: str = "code_chunks_colbert",
    extra_where: str = "",
    extra_params: Sequence = (),
) -> list[tuple[int, float]]:
    """v1.34.0+ (E10) — ColBERT MaxSim search via the multi-vector
    sidecar.

    Returns ``[(rowid, max_sim_score), ...]`` top-K descending. The
    ``base_table`` parameter is the chunk table (e.g. ``code_chunks``);
    ``sidecar_table`` defaults to ``<base_table>_colbert`` — pass
    explicitly for other indexers.

    Returns ``[]`` (degrades gracefully) when:

      - sidecar table absent (pre-v1.34 db), OR
      - ``_colbert.is_available()`` False (deps / model missing), OR
      - no rows in the sidecar yet (KAIZEN_COLBERT_ENABLE wasn't on
        during indexing).
    """
    # Sidecar present?
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name=?",
        (sidecar_table,),
    ).fetchone()
    if row is None:
        return []
    import _colbert  # lazy local import — heavy deps
    if not _colbert.is_available():
        return []
    q_mat = _colbert.encode_colbert(query)
    if q_mat is None or getattr(q_mat, "size", 0) == 0:
        return []

    where = ""
    if extra_where:
        where = f" WHERE {extra_where}"
    rows = conn.execute(
        f"SELECT chunk_id, vectors FROM {sidecar_table}{where}",
        list(extra_params),
    ).fetchall()
    if not rows:
        return []

    scored: list[tuple[int, float]] = []
    for r in rows:
        d_mat = _colbert.deserialize(bytes(r[1]))
        if d_mat is None:
            continue
        s = _colbert.max_sim_score(q_mat, d_mat)
        if s > 0:
            scored.append((int(r[0]), s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ─── Hybrid (linear) ─────────────────────────────────────────────────


def _minmax_normalize(scored: Iterable[tuple[int, float]]) -> dict[int, float]:
    """Min-max normalize a (id, score) list into a {id: [0,1]} dict.

    All-same scores → all 1.0 (the standard convention)."""
    scored = list(scored)
    if not scored:
        return {}
    scores = [s for _, s in scored]
    lo, hi = min(scores), max(scores)
    span = hi - lo
    if span <= 0:
        return {i: 1.0 for i, _ in scored}
    return {i: (s - lo) / span for i, s in scored}


def hybrid_search(
    conn: sqlite3.Connection,
    base_table: str,
    query: str,
    top_k: int = 10,
    *,
    candidate_pool: int = 50,
    alpha: float = 0.5,
    fusion: str = "linear",
    extra_where: str = "",
    extra_params: Sequence = (),
    use_sparse: bool = True,
) -> list[tuple[int, float]]:
    """BM25 + dense (+ optional SPLADE sparse), fused.

    `fusion="linear"` (default) — min-max normalize each path, then
    `score = alpha*dense + (1-alpha)*bm25`. Matches Onyx's Vespa rank
    expression executed client-side. The linear path ignores sparse —
    blending three ranks with one `alpha` is ambiguous; opt into the
    `rrf` path when sparse is enabled.

    `fusion="rrf"` (v1.31.0+) — reciprocal-rank-fusion: rank-only
    scoring `1 / (k + rank)`, no normalization step. More robust to
    score-distribution differences between the paths; doesn't require
    an `alpha` choice. With `use_sparse=True` (default), folds the
    SPLADE sparse ranking in as a third source. Weights are
    `[alpha, (1-alpha)/2, (1-alpha)/2]` for `[dense, bm25, sparse]`
    when sparse has results; otherwise `[alpha, 1-alpha]` over
    `[dense, bm25]` (back-compat with pre-E9).

    Each sub-retrieval pulls `candidate_pool` candidates (Onyx uses
    1000; 50 is fine for SQLite-scale corpora).

    use_sparse: when True, attempt sparse_search and fold into RRF if
                non-empty. Off by default for linear fusion (see
                above). The cost when sparse is unindexed is one
                PRAGMA probe — cheap."""
    dense = dense_search(
        conn, base_table, query, candidate_pool,
        extra_where=extra_where, extra_params=extra_params,
    )
    bm25 = bm25_search(conn, base_table, query, candidate_pool)

    if fusion == "rrf":
        rankings: list[Sequence[tuple[int, float]]] = [dense, bm25]
        weights: list[float] = [alpha, 1.0 - alpha]
        if use_sparse:
            sparse = sparse_search(
                conn, base_table, query, candidate_pool,
                extra_where=extra_where, extra_params=extra_params,
            )
            if sparse:
                # 3-way RRF: split the non-dense weight evenly between
                # bm25 and sparse so dense weight stays at `alpha`.
                non_dense = 1.0 - alpha
                rankings.append(sparse)
                weights = [alpha, non_dense / 2.0, non_dense / 2.0]
        return reciprocal_rank_fusion(
            rankings, weights=weights, k=60, top_k=top_k,
        )

    dense_n = _minmax_normalize(dense)
    bm25_n = _minmax_normalize(bm25)
    all_ids = set(dense_n) | set(bm25_n)
    fused: list[tuple[int, float]] = []
    for rid in all_ids:
        d = dense_n.get(rid, 0.0)
        b = bm25_n.get(rid, 0.0)
        score = alpha * d + (1 - alpha) * b
        fused.append((rid, score))
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused[:top_k]


# ─── Reciprocal Rank Fusion (for multi-query expansion) ──────────────


# ─── E2: cross-encoder reranking ─────────────────────────────────────
#
# Cross-encoders score (query, candidate) pairs directly — slower per
# pair than bi-encoder cosine but materially better at relevance for
# the top-K (typical +50-200ms / query but ~5-15% NDCG@10 win on
# domain-specific corpora).
#
# This module is stub-friendly: pass `score_fn` for tests to avoid
# loading a real model (CrossEncoder pulls ~80-130MB ST weights).

_cross_encoder = None  # module-level cache; loaded on first use


def _default_cross_encoder_model() -> str:
    """KAIZEN_RERANK_MODEL — defaults to cross-encoder/ms-marco-MiniLM-L-6-v2
    (90 MB, fast). For multilingual or domain-specific corpora, point at
    BAAI/bge-reranker-base (~280 MB) or jinaai/jina-reranker-v2-base."""
    import os as _os
    return _os.environ.get(
        "KAIZEN_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )


def _load_cross_encoder():
    """Lazy load. Returns None when sentence-transformers isn't installed."""
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except ImportError:
        return None
    _cross_encoder = CrossEncoder(_default_cross_encoder_model())
    return _cross_encoder


def cross_encoder_rerank(
    query: str,
    candidates: Sequence[tuple[int, str]],
    *,
    top_k: int = 10,
    score_fn=None,
) -> list[tuple[int, float]]:
    """Rerank `(id, text)` pairs by cross-encoder relevance to `query`.

    Returns sorted `[(id, score), ...]` top-K descending. Higher score =
    more relevant. Stable for ties.

    candidates: list of (row_id, candidate_text) pairs — typically the
                top 30-50 from a hybrid bi-encoder search.
    score_fn:   optional `(query, candidates_text_list) -> list[float]`
                stub for tests. When None, the cross-encoder is lazy-
                loaded; if sentence-transformers is unavailable, returns
                candidates unchanged (preserving input order)."""
    if not candidates:
        return []
    if score_fn is None:
        ce = _load_cross_encoder()
        if ce is None:
            # No-rerank fallback — preserve input order as scored.
            return [(rid, 0.0) for rid, _ in candidates[:top_k]]
        score_fn = lambda q, texts: ce.predict([(q, t) for t in texts])
    texts = [t for _, t in candidates]
    scores = list(score_fn(query, texts))
    if len(scores) != len(candidates):
        raise ValueError(
            f"cross_encoder_rerank: score_fn returned {len(scores)} "
            f"scores for {len(candidates)} candidates"
        )
    scored = list(zip([rid for rid, _ in candidates], scores))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[tuple[int, float]]],
    *,
    weights: Sequence[float] | None = None,
    k: int = 50,
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """RRF across multiple ranked lists (e.g. semantic + keyword + LLM-rephrased).

    Onyx's `weighted_reciprocal_rank_fusion()` in
    `backend/onyx/tools/tool_implementations/search/search_utils.py`,
    weights default `[1.3, 1.0, 0.7, 0.5]` for
    `[semantic, keyword, expansion_1, expansion_2]` and `k=50`.

    Score per id: `sum_i (weights[i] / (k + rank_in_list_i))`. Higher = better."""
    if not rankings:
        return []
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError(
            f"reciprocal_rank_fusion: weights length {len(weights)} != "
            f"rankings length {len(rankings)}"
        )

    fused: dict[int, float] = {}
    for w, ranking in zip(weights, rankings):
        for rank, (rid, _score) in enumerate(ranking):
            fused[rid] = fused.get(rid, 0.0) + w / (k + rank + 1)

    out = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    return out[:top_k]
