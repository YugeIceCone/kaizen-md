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
"""kaizen knowledge-search-mcp — MCP server exposing semantic search over
the kaizen knowledge SQLite index. FastMCP + async wrappers around
`knowledge_index.py` data-returning helpers (do_*).

Sibling of `trace_mcp.py` (which exposes the trace event index). Same
pattern, same model, same SQLite-shared-with-CLI shape.

Tools (Claude can invoke):

  knowledge_search(query, top_k=10, source="")
    Semantic search over brain notes / plans / backlog / schemas / persona.
    Optional `source` filters to one of: brain-note, plan, backlog,
    schema, persona.

  knowledge_index_status()
    Index health — total items, model, dim, last indexed ts, counts by
    source.

  knowledge_index_run(embed_body=False)
    Incremental index pass. Returns {new, skipped, stale_removed, total}.
    `embed_body=True` opts in to embedding the snippet body (privacy:
    default is signature-only).

  knowledge_get(item_id)
    Fetch one indexed item by SQLite id (returned by search results).

  knowledge_recent(limit=20, source="")
    Latest N items by `updated_at` — no semantic ranking. Use for
    "what's been added lately?" queries.

## State

Single SQLite DB at `~/.claude/.kaizen-knowledge/index.db`. Shared with
the `kaizen-knowledge` CLI / slash command. MCP server keeps a
sentence-transformers model loaded across tool calls (~500MB RAM after
first call; instant embeddings thereafter).

## Spawning

Registered in `.mcp.json` as `kaizen-knowledge-search`. Claude Code
spawns on-demand when the first `mcp__plugin_kaizen_kaizen-knowledge-search__*`
tool fires.
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
    import knowledge_index as ki  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-knowledge-search-mcp: missing dep: {e}\n"
        "Run: kaizen-knowledge index (first run auto-installs deps via uv)\n"
    )
    sys.exit(1)

mcp = FastMCP("knowledge-search")

@mcp.tool()
async def knowledge_search(
    query: str,
    top_k: int = 10,
    source: str = "",
) -> list[dict]:
    """Semantic search over the kaizen knowledge SQLite index.

    query: natural-language description of what to find.
    top_k: max results (default 10).
    source: optional filter — one of "brain-note", "plan", "backlog",
            "schema", "persona". Empty string = all sources.

    Returns list of {score, id, source, source_path, title, snippet,
    tags, updated_at}. Score is cosine similarity in [0, 1]; higher =
    closer to query."""
    return ki.do_search(query, top_k=top_k, source=source or None)

@mcp.tool()
async def knowledge_index_status() -> dict:
    """Index health: total items, model, dim, last_indexed_ts, counts
    by source. Call this first to verify the index is built + current."""
    return ki.do_stats()

@mcp.tool()
async def knowledge_index_run(embed_body: bool = False) -> dict:
    """Incremental index pass. Skips already-indexed items via sha
    dedup; removes stale entries. Returns {new, skipped, stale_removed,
    total, model}.

    embed_body: if True, also embed the snippet body (first ~400 chars
    of each item). Default False keeps embeddings privacy-safe
    (signature: source + title + tags only)."""
    return ki.do_index(embed_body=embed_body)

@mcp.tool()
async def knowledge_get(item_id: int) -> dict:
    """Fetch one indexed item by SQLite id (returned by knowledge_search)."""
    r = ki.do_get(item_id)
    return r if r else {"error": f"id={item_id} not found"}

@mcp.tool()
async def knowledge_recent(limit: int = 20, source: str = "") -> list[dict]:
    """Latest N items by `updated_at` — no semantic ranking. Use for
    "what was added / changed recently?" Combine with source filter for
    narrowing (e.g. 'plan' for recently-updated plan files)."""
    if not ki.DB_PATH.exists():
        return []
    conn = ki.open_db(create=False)
    sql = "SELECT id, source, source_path, title, snippet, tags, updated_at FROM knowledge_items"
    params: list = []
    if source:
        sql += " WHERE source = ?"
        params.append(source)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    import json as _json
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "source": r["source"],
                "source_path": r["source_path"],
                "title": r["title"],
                "snippet": r["snippet"],
                "tags": _json.loads(r["tags"] or "[]"),
                "updated_at": r["updated_at"],
            }
        )
    return out

if __name__ == "__main__":
    mcp.run()
