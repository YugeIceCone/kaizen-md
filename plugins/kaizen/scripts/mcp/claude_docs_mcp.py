#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
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
"""kaizen claude-docs-search-mcp — MCP server exposing semantic search over
the local ericbuess/claude-code-docs mirror.

Sibling of knowledge_mcp.py / onboard_mcp.py / trace_mcp.py — same FastMCP
pattern, same model, same SQLite-shared-with-CLI shape. Wraps `do_*`
helpers in claude_docs_index.py so the CLI and MCP serve identical
results.

Tools (Claude can invoke):

  claude_docs_search(query, top_k=8)
    Cosine top-k over chunked embeddings. Returns ranked hits with
    {score, id, path, chunk_idx, section, snippet}.

  claude_docs_stats()
    Index meta — {files, chunks, model, dim, backend_kind,
    last_indexed_ts}.

  claude_docs_get(chunk_id)
    Fetch one chunk's full text by id (from search results).

  claude_docs_list_files(limit=200)
    File-level index (path, sha, chunk_count, title, bytes,
    updated_at) without embeddings — useful for "what topics are
    indexed?" queries.

  claude_docs_index_run()
    Trigger an incremental index pass. Returns the same shape as
    `python3 claude_docs_index.py index` exit JSON.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — until indexers move back / consumers move forward
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "indexers"))

try:
    from fastmcp import FastMCP
    import claude_docs_index as cdi  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-claude-docs-mcp: missing dep: {e}\n"
        "Run: kaizen-claude-docs index (first run auto-installs deps via uv)\n"
    )
    sys.exit(1)


mcp = FastMCP("claude-docs")


@mcp.tool()
async def claude_docs_search(query: str, top_k: int = 8) -> list[dict]:
    """Semantic search over the local Claude API/Code/SDK docs mirror.

    query: natural-language description of what to find.
    top_k: max results (default 8).

    Returns list of {score, id, path, chunk_idx, section, snippet}.
    `score` is cosine similarity in [0, 1]; higher = closer.
    `path` is relative to the docs source dir; `chunk_idx` is the
    chunk index within that file; `section` is the nearest preceding
    H1/H2/H3 header. Pass the returned `id` to claude_docs_get for
    the full chunk text."""
    return cdi.do_search(query, top_k=top_k)


@mcp.tool()
async def claude_docs_stats() -> dict:
    """Index meta — {exists, files, chunks, model, dim, backend_kind,
    last_indexed_ts, size_bytes, src, db}. Call this first to verify
    the index is built before searching."""
    return cdi.do_stats()


@mcp.tool()
async def claude_docs_get(chunk_id: int) -> dict:
    """Fetch one chunk's full text by SQLite id (from search results).

    Returns {id, path, chunk_idx, char_start, char_end, section, text}
    or {"error": ...} if not found."""
    r = cdi.do_get(chunk_id)
    return r if r else {"error": f"chunk id={chunk_id} not found"}


@mcp.tool()
async def claude_docs_list_files(limit: int = 200) -> list[dict]:
    """File-level listing of the index (no embeddings).

    Returns up to `limit` files as {path, sha, chunk_count, title,
    bytes, updated_at}. Use for `what topics are indexed?` queries
    before deciding which sub-query to run."""
    return cdi.do_list_files(limit=limit)


@mcp.tool()
async def claude_docs_index_run() -> dict:
    """Trigger an incremental index pass (sha-deduped per file).

    Returns {indexed, skipped, removed, total_files, total_chunks,
    model, db}."""
    # Synthesize a Namespace-like object since cmd_index takes argparse args.
    class _A:
        src = None
    return cdi.cmd_index(_A())


if __name__ == "__main__":
    mcp.run()
