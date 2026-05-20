#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen rerank-mcp — cross-encoder reranking as a standalone MCP server.

Wraps `_search.cross_encoder_rerank` so any consumer (CC, Codex, ad-hoc
shell) can rerank a candidate list against a query without depending on
a specific kaizen index. Pairs with the bi-encoder hybrid search exposed
by knowledge / onboard / claude-docs / scrape MCPs — query those first,
pass the top-30 hits through this rerank, take top-5.

## Tool

  embed_rerank(query, candidates, top_k=10)
    Score `candidates` (list of {"id": int, "text": str}) against `query`
    using a cross-encoder. Returns the top `top_k` reordered by score.

    Defaults model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~90 MB).
    Override via KAIZEN_RERANK_MODEL env var.

## When to use

- After hybrid bi-encoder search returned candidates whose relevance is
  uncertain (low or close-together scores).
- Domain-specific corpora where bi-encoder cosine doesn't capture intent.
- Final re-ranking of a UNION across multiple indexes.

## When NOT to use

- Latency-sensitive paths (cross-encoder adds 50-200ms per query).
- Trivial single-keyword queries where BM25 wins outright.

## Spawning

Registered in .mcp.json as `rerank`. CC spawns on first
`mcp__plugin_kaizen_rerank__*` invocation.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "handlers"))

try:
    from fastmcp import FastMCP
    import _search as kz_search  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-rerank-mcp: missing dep: {e}\n"
        "Ensure mcp>=1.0 is installed (uv handles this automatically).\n"
    )
    sys.exit(1)

mcp = FastMCP("kaizen-rerank")

@mcp.tool()
async def embed_rerank(
    query: str,
    candidates: list[dict],
    top_k: int = 10,
) -> list[dict]:
    """Rerank candidates by cross-encoder relevance to query.

    query:      natural-language query.
    candidates: list of {"id": <opaque>, "text": <string>} dicts. The id
                is echoed back so callers can correlate. text is the
                content scored against the query.
    top_k:      max results (default 10).

    Returns sorted [{"id": ..., "text": ..., "score": <float>}, ...]
    descending by score. When sentence-transformers is unavailable
    (e.g. minimal Codex install), returns the input order with score=0
    so callers don't crash.

    Cost: ~50-200ms per query on the default MiniLM model. For larger
    candidate lists (>100), consider pre-filtering with bi-encoder
    cosine first."""
    if not query or not candidates:
        return []
    pairs = [(c.get("id"), c.get("text") or "") for c in candidates]
    scored = kz_search.cross_encoder_rerank(query, pairs, top_k=top_k)
    # Build output dicts preserving original `text`
    id_to_text = {c.get("id"): c.get("text") or "" for c in candidates}
    return [
        {"id": rid, "text": id_to_text.get(rid, ""), "score": float(score)}
        for rid, score in scored
    ]

@mcp.tool()
async def embed_rerank_status() -> dict:
    """Report the cross-encoder model that would be used + whether
    sentence-transformers is importable in this environment."""
    import importlib.util
    has_st = importlib.util.find_spec("sentence_transformers") is not None
    return {
        "model": kz_search._default_cross_encoder_model(),
        "sentence_transformers_available": has_st,
        "fallback_behavior": "input order preserved with score=0"
                             if not has_st else "cross-encoder predict",
    }

if __name__ == "__main__":
    mcp.run()
