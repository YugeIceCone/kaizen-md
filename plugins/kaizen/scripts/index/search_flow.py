#!/usr/bin/env -S uv run --script
# consolidated-cli-parent: flow
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
#     "sqlite-vec>=0.1.6",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""kaizen search_flow — pocketflow-shaped semantic-search pipeline.

Wraps `onboard_index.do_search` / `_search.hybrid_search` as a chain
of explicit AsyncNode steps over a shared store. Same vectorized
matmul + BM25 + fusion logic as the inline path; the Node+Flow
discipline buys us: per-stage timing, testable nodes, easy fan-out
to sibling indexers (knowledge, trace, scrape), and a single seam to
swap in sqlite-vec when corpora grow past the matmul-cosine cliff.

## Pipeline

```text
    EmbedQueryNode
        ├── dense pool ───┐
        └── bm25 pool ────┤
                          ▼
                    FusionNode
                          │
                          ▼
                     RerankNode  (optional; opt-in via store["rerank"])
                          │
                          ▼
                   CitationNode
                          │
                          ▼
                       results
```

The `FanOutSearchNode` runs the dense + BM25 paths concurrently via
`asyncio.gather`; both paths share the same embedded query vector
produced once in `EmbedQueryNode`. At shodan-scale (~3000 chunks)
parallel paths complete in <50ms total.

## Shared-store contract

Inputs:
  store["query"]            — natural-language query (str, required)
  store["root"]             — project root path (Path, required)
  store["top_k"]            — final result count (int, default 10)
  store["candidate_pool"]   — per-path candidate cap (int, default 50)
  store["alpha"]            — fusion weight (float, default 0.5)
  store["fusion"]           — "linear" | "rrf" (default "linear")
  store["language"]         — optional language filter
  store["rerank"]           — bool, opt-in cross-encoder rerank (default False)
  store["legacy"]           — bool, search code_files instead of code_chunks

Outputs (added by nodes):
  store["query_vec"]        — float32 numpy array, normalized
  store["dense_pool"]       — [(id, score), ...]
  store["bm25_pool"]        — [(id, score), ...]
  store["fused"]            — [(id, score), ...] (top_k after fusion)
  store["results"]          — list[dict] — final result records w/ citation
  store["_timing"][Node]    — per-node wall time (ms)

## Future hooks

- `Sqlite-vec acceleration` — drop-in at `DenseSearchNode.exec_async`:
  if `conn.enable_load_extension(True)` + `sqlite_vec.load(conn)` succeed,
  query `vec_search` virtual table for KNN instead of stacking + matmul.
  Cuts dense path from O(N) to O(log N) once N > ~50K chunks.
- `Cross-encoder rerank` — wire `RerankNode` to onnx.rs-style cross-encoder
  once the embed backend supports it. Hook is already plumbed (store["rerank"]).
- `Multi-query fusion` — chain N EmbedQueryNodes (semantic + keyword +
  LLM-rephrased) and use `reciprocal_rank_fusion` over all N pools.
  See _search.py:reciprocal_rank_fusion for the weighted variant.

Usage:

    import asyncio
    from search_flow import build_search_flow

    flow = build_search_flow()
    store = {"query": "auth token validation", "root": Path("."), "top_k": 10}
    asyncio.run(flow.run_async(store))
    for r in store["results"]:
        print(f"{r['score']:.3f}  {r['path']}")
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — until indexers move back / consumers move forward
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))

# flow.py provides the AsyncNode/AsyncFlow primitives (see
# references/node-flow.md). Local import to keep search_flow runnable
# even when flow.py is unimportable (rare).
import flow as _flow  # noqa: E402
import _search as _kz_search  # noqa: E402
import _embed as _kz_embed  # noqa: E402
import _chunk as _kz_chunk  # noqa: E402
import onboard_index as _oi  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-search", tool_version="1.0.0")


# ─── Nodes ───────────────────────────────────────────────────────────


class EmbedQueryNode(_flow.AsyncNode):
    """Embed the query into a unit vector. One LLM/HTTP round-trip;
    cached implicitly by the embed backend resolver."""

    async def prep_async(self, store: dict) -> str:
        q = store.get("query") or ""
        if not q.strip():
            raise ValueError("EmbedQueryNode: store['query'] is empty")
        return q

    async def exec_async(self, query: str) -> Any:
        np = _kz_embed.require_numpy()
        prefixed = _kz_chunk.apply_query_prefix(query)
        blob, _dim = await asyncio.to_thread(_kz_embed.embed_one, prefixed)
        vec = np.frombuffer(blob, dtype=np.float32)
        return vec / (np.linalg.norm(vec) + 1e-12)

    async def post_async(self, store: dict, prep_res: str, exec_res: Any) -> str:
        store["query_vec"] = exec_res
        return "default"


class FanOutSearchNode(_flow.AsyncNode):
    """Run dense + BM25 retrieval in parallel via asyncio.gather.

    Both paths share the same `query_vec` produced by EmbedQueryNode.
    Each pulls `candidate_pool` candidates; FusionNode merges the
    union."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "root": store["root"],
            "query": store["query"],
            "pool": store.get("candidate_pool", 50),
            "language": store.get("language"),
            "legacy": store.get("legacy", False),
            "backend": store.get("dense_backend", "auto"),
        }

    async def exec_async(self, prep: dict) -> dict:
        # Run both paths in parallel via asyncio.gather. SQLite
        # connections are per-thread-only, so each path opens its own
        # connection INSIDE the worker thread (via the _run_* helpers).
        # WAL journal mode (set in onboard_index.open_db) makes the
        # concurrent reads safe.
        base_table = "code_files" if prep["legacy"] else "code_chunks"
        extra_where = ""
        extra_params: list = []
        if prep["language"]:
            extra_where = "language = ?"
            extra_params = [prep["language"]]
        dense_task = asyncio.to_thread(
            self._run_dense,
            prep["root"], base_table, prep["query"], prep["pool"],
            extra_where, extra_params, prep["backend"],
        )
        bm25_task = asyncio.to_thread(
            self._run_bm25,
            prep["root"], base_table, prep["query"], prep["pool"],
        )
        dense, bm25 = await asyncio.gather(dense_task, bm25_task)
        return {"dense": dense, "bm25": bm25, "base_table": base_table}

    @staticmethod
    def _run_dense(root: Path, base_table: str, query: str, pool: int,
                   extra_where: str, extra_params: list,
                   backend: str = "auto") -> list:
        """Route to the best available dense backend.

        backend = "auto" (default):
            try sqlite-vec → int8 → float32, falling back on failure.
        backend = "vec":  sqlite-vec KNN; falls back to "q8" / "float32" if unavailable.
        backend = "q8":   int8-quantized cosine; falls back to "float32" if q8 column empty.
        backend = "float32" (= the legacy vectorized matmul; always works).
        """
        conn = _oi.open_db(root, create=False)
        try:
            if backend in ("auto", "vec"):
                vec_result = _kz_search.dense_search_vec(
                    conn, base_table, query, pool,
                )
                if vec_result is not None:
                    return vec_result
                if backend == "vec":
                    sys.stderr.write(
                        "kaizen search: backend='vec' unavailable; falling back to q8/float32\n"
                    )
            if backend in ("auto", "q8"):
                # dense_search_q8 already falls back to dense_search
                # internally when the column is missing or empty.
                return _kz_search.dense_search_q8(
                    conn, base_table, query, pool,
                    extra_where=extra_where, extra_params=extra_params,
                )
            return _kz_search.dense_search(
                conn, base_table, query, pool,
                extra_where=extra_where, extra_params=extra_params,
            )
        finally:
            conn.close()

    @staticmethod
    def _run_bm25(root: Path, base_table: str, query: str, pool: int) -> list:
        conn = _oi.open_db(root, create=False)
        try:
            return _kz_search.bm25_search(conn, base_table, query, pool)
        finally:
            conn.close()

    async def post_async(self, store: dict, prep: dict, exec_res: dict) -> str:
        store["dense_pool"] = exec_res["dense"]
        store["bm25_pool"] = exec_res["bm25"]
        store["_base_table"] = exec_res["base_table"]
        return "default"


class FusionNode(_flow.AsyncNode):
    """Merge dense + bm25 pools via the configured fusion strategy."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "dense": store.get("dense_pool", []),
            "bm25": store.get("bm25_pool", []),
            "alpha": store.get("alpha", 0.5),
            "fusion": store.get("fusion", "linear"),
            "top_k": store.get("top_k", 10),
        }

    async def exec_async(self, prep: dict) -> list[tuple[int, float]]:
        if prep["fusion"] == "rrf":
            return _kz_search.reciprocal_rank_fusion(
                [prep["dense"], prep["bm25"]],
                weights=[prep["alpha"], 1.0 - prep["alpha"]],
                k=60,
                top_k=prep["top_k"],
            )
        # Linear (min-max normalize each path, weighted sum).
        from _search import _minmax_normalize  # private helper, intentional
        dn = _minmax_normalize(prep["dense"])
        bn = _minmax_normalize(prep["bm25"])
        all_ids = set(dn) | set(bn)
        a = prep["alpha"]
        scored = [(rid, a * dn.get(rid, 0.0) + (1 - a) * bn.get(rid, 0.0))
                  for rid in all_ids]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: prep["top_k"]]

    async def post_async(self, store: dict, prep: dict, exec_res: list) -> str:
        store["fused"] = exec_res
        return "rerank" if store.get("rerank") else "citation"


class RerankNode(_flow.AsyncNode):
    """Cross-encoder rerank — opt-in via store["rerank"].

    v1.31.0+: placeholder; pass-through when no rerank backend is
    configured. Hook for the future onnx.rs-style cross-encoder
    (`shodan-retrieval::semantic::embeddings::CrossEncoderRerankerTool`
    is the reference shape)."""

    async def prep_async(self, store: dict) -> list:
        return store.get("fused", [])

    async def exec_async(self, fused: list) -> list:
        # TODO(v1.32.0): wire cross-encoder rerank. For now, identity.
        return fused

    async def post_async(self, store: dict, prep: list, exec_res: list) -> str:
        store["reranked"] = exec_res
        return "citation"


class CitationNode(_flow.AsyncNode):
    """Resolve fused/reranked (id, score) tuples to full result rows.

    Joins back to code_files for path / language / sloc / bytes; if
    base_table is code_chunks, also pulls char_start/char_end for
    citation. Output shape matches the legacy `do_search` return so
    callers can swap the flow in without changing downstream code."""

    async def prep_async(self, store: dict) -> dict:
        ranked = store.get("reranked") or store.get("fused", [])
        return {
            "root": store["root"],
            "ranked": ranked,
            "base_table": store.get("_base_table", "code_chunks"),
        }

    async def exec_async(self, prep: dict) -> list[dict]:
        ranked = prep["ranked"]
        if not ranked:
            return []
        # Open conn inside the worker thread (sqlite per-thread rule).
        return await asyncio.to_thread(
            self._resolve_in_thread, prep["root"], prep["base_table"], ranked,
        )

    @staticmethod
    def _resolve_in_thread(root: Path, base_table: str,
                           ranked: list[tuple[int, float]]) -> list[dict]:
        conn = _oi.open_db(root, create=False)
        try:
            return CitationNode._resolve(conn, base_table, ranked)
        finally:
            conn.close()

    @staticmethod
    def _resolve(conn: sqlite3.Connection, base_table: str,
                 ranked: list[tuple[int, float]]) -> list[dict]:
        if base_table == "code_chunks":
            sql = (
                "SELECT c.id AS chunk_id, c.chunk_idx, c.char_start, c.char_end, "
                "       c.text AS chunk_text, c.language, "
                "       f.id AS file_id, f.path, f.bytes, f.sloc, f.snippet, f.updated_at "
                "FROM code_chunks c JOIN code_files f ON f.id = c.file_id "
                "WHERE c.id = ?"
            )
            results: list[dict] = []
            for cid, score in ranked:
                row = conn.execute(sql, (cid,)).fetchone()
                if not row:
                    continue
                results.append({
                    "score": round(score, 4),
                    "id": row["file_id"],
                    "path": row["path"],
                    "language": row["language"],
                    "bytes": row["bytes"],
                    "sloc": row["sloc"],
                    "snippet": row["snippet"],
                    "updated_at": row["updated_at"],
                    "matched_chunk_idx": row["chunk_idx"],
                    "char_range": [row["char_start"], row["char_end"]],
                })
            return results
        # Legacy code_files path.
        sql = (
            "SELECT id, path, language, bytes, sloc, snippet, updated_at "
            "FROM code_files WHERE id = ?"
        )
        results = []
        for fid, score in ranked:
            row = conn.execute(sql, (fid,)).fetchone()
            if not row:
                continue
            results.append({
                "score": round(score, 4),
                "id": row["id"],
                "path": row["path"],
                "language": row["language"],
                "bytes": row["bytes"],
                "sloc": row["sloc"],
                "snippet": row["snippet"],
                "updated_at": row["updated_at"],
            })
        return results

    async def post_async(self, store: dict, prep: dict, exec_res: list) -> None:
        store["results"] = exec_res
        return None  # terminal


# ─── Builder + sync wrapper ──────────────────────────────────────────


def build_search_flow() -> _flow.AsyncFlow:
    """Construct the canonical search flow.

    embed → fan-out (dense+bm25) → fusion → [rerank?] → citation."""
    embed = EmbedQueryNode()
    fan_out = FanOutSearchNode()
    fuse = FusionNode()
    rerank = RerankNode()
    cite = CitationNode()
    f = _flow.AsyncFlow(start=embed)
    f.add_successor(embed, "default", fan_out)
    f.add_successor(fan_out, "default", fuse)
    f.add_successor(fuse, "citation", cite)
    f.add_successor(fuse, "rerank", rerank)
    f.add_successor(rerank, "citation", cite)
    return f


def search(root: Path, query: str, *, top_k: int = 10,
           language: str | None = None, alpha: float = 0.5,
           fusion: str = "linear", legacy: bool = False,
           dense_backend: str = "auto") -> list[dict]:
    """Sync wrapper — convenient for shell scripts and one-shot CLIs.

    Drop-in shape-compatible with `onboard_index.do_search`.

    `dense_backend` selects the cosine path: "auto" (try vec → q8 →
    float32), "vec" (sqlite-vec only, falls back on failure), "q8"
    (int8 quantized, falls back when column empty), "float32"
    (the always-available vectorized matmul)."""
    store: dict = {
        "root": root,
        "query": query,
        "top_k": top_k,
        "alpha": alpha,
        "fusion": fusion,
        "language": language,
        "legacy": legacy,
        "dense_backend": dense_backend,
    }
    f = build_search_flow()
    asyncio.run(f.run_async(store))
    return store.get("results", [])


# ─── CLI ─────────────────────────────────────────────────────────────


def main():
    import argparse
    import json
    p = argparse.ArgumentParser(
        prog="search_flow.py",
        description="kaizen pocketflow semantic-search pipeline",
    )
    p.add_argument("query", help="natural-language query")
    p.add_argument("--root", default=".", help="project root (default: cwd)")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--language", help="filter by language")
    p.add_argument("--alpha", type=float, default=0.5,
                   help="dense weight in fusion (0..1, default 0.5)")
    p.add_argument("--fusion", choices=["linear", "rrf"], default="linear")
    p.add_argument("--backend", choices=["auto", "float32", "q8", "vec"],
                   default="auto",
                   help="dense path backend: auto=vec→q8→float32, "
                        "q8=int8 quant, vec=sqlite-vec KNN (default: auto)")
    p.add_argument("--legacy", action="store_true",
                   help="search code_files (whole-file) instead of code_chunks")
    p.add_argument("--json", action="store_true", help="emit JSON results")
    p.add_argument("--timing", action="store_true",
                   help="show per-node timing alongside results")
    args = p.parse_args()
    root = Path(args.root).resolve()
    store: dict = {
        "root": root, "query": args.query, "top_k": args.top_k,
        "language": args.language, "alpha": args.alpha,
        "fusion": args.fusion, "legacy": args.legacy,
        "dense_backend": args.backend,
    }
    f = build_search_flow()
    asyncio.run(f.run_async(store))
    results = store.get("results", [])
    if args.json:
        _emit(results, counts={"results": len(results) if hasattr(results, "__len__") else 0})
    else:
        if not results:
            print("(no results — run `kaizen onboard reindex` first)", file=sys.stderr)
        for r in results:
            cite = ""
            if "char_range" in r:
                cite = f" [chunk {r['matched_chunk_idx']} chars {r['char_range'][0]}..{r['char_range'][1]}]"
            print(f"  {r['score']:.3f}  {r['language']:<10} {r['path']}{cite}")
    if args.timing:
        print("--- timing (ms) ---", file=sys.stderr)
        for name, ms in store.get("_timing", {}).items():
            print(f"  {name:<22} {ms} ms", file=sys.stderr)


if __name__ == "__main__":
    main()
