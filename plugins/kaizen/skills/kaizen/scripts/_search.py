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

    cur.executescript(f"""
        CREATE VIRTUAL TABLE {fts} USING fts5(
            text,
            content='{base_table}',
            content_rowid='id'
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
    [(rowid, cosine_score), ...] sorted best-first."""
    import _chunk  # local import — avoid circular if _chunk grows
    np = _embed.require_numpy()
    q = _chunk.apply_query_prefix(query) if apply_prefix else query
    qblob, _ = _embed.embed_one(q)
    qvec = np.frombuffer(qblob, dtype=np.float32)
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)
    q_dim = qvec.shape[0]

    where = f" WHERE embedding IS NOT NULL{(' AND ' + extra_where) if extra_where else ''}"
    rows = conn.execute(
        f"SELECT id, embedding FROM {base_table}{where}",
        list(extra_params),
    ).fetchall()

    scored: list[tuple[int, float]] = []
    skipped = 0
    for r in rows:
        evec = np.frombuffer(r[1], dtype=np.float32)
        if evec.shape[0] != q_dim:
            skipped += 1
            continue
        score = float(np.dot(qnorm, evec / (np.linalg.norm(evec) + 1e-12)))
        scored.append((int(r[0]), score))
    if skipped:
        sys.stderr.write(
            f"kaizen search: skipped {skipped} row(s) with dim != {q_dim} — "
            "reindex after embed-backend change\n"
        )
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
    extra_where: str = "",
    extra_params: Sequence = (),
) -> list[tuple[int, float]]:
    """BM25 + dense, linearly fused: `score = alpha*dense + (1-alpha)*bm25`.

    Matches Onyx's Vespa rank expression but executed client-side. Each
    sub-retrieval pulls `candidate_pool` candidates (Onyx uses 1000;
    50 is fine for SQLite-scale corpora). The union of the two pools
    is scored; rows that appeared in only one path keep their score
    on that side and 0 on the missing side (pre-normalize)."""
    dense = dense_search(
        conn, base_table, query, candidate_pool,
        extra_where=extra_where, extra_params=extra_params,
    )
    bm25 = bm25_search(conn, base_table, query, candidate_pool)

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
