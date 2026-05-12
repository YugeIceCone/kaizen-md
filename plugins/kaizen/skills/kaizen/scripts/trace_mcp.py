#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp>=1.0",
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
"""kaizen trace-search-mcp — MCP server exposing semantic-search over the
kaizen trace SQLite index. FastMCP + async wrappers around `trace_index.py`.

**CPU-only torch** — MCP server is long-running and rarely benefits from
GPU for short embedding calls. For batch reindex with GPU, use the CLI:
`KAIZEN_TRACE_GPU=1 kaizen-trace-index index`.

Tools (Claude can invoke):

  trace_search(query, top_k=10, src="", sid="", evt="", since="")
    Semantic search. Returns list of matched events with similarity scores.
    Filters compose with SQL pre-filter for speed.

  trace_index_status()
    Indexed count, model, earliest/latest ts, last indexed ts.

  trace_index_run(embed_data=False)
    Incremental re-index of new events not yet in the SQLite store.

  trace_get(event_id)
    Fetch the full event by id (returned by search results).

  trace_recent(limit=20, src="")
    Latest N events without semantic ranking — fast list.

## State

Single SQLite DB at `~/.claude/.kaizen-trace/index.db`. Shared with
`kaizen-trace-index` CLI. MCP server keeps a sentence-transformers
model loaded across tool calls (~500MB RAM after first call; instant
embeddings thereafter).

## Spawning

Registered in `.mcp.json` as `kaizen-trace-search`. CC spawns on-demand
when the first `mcp__plugin_kaizen_kaizen-trace-search__*` tool fires.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from mcp.server.fastmcp import FastMCP
    import trace_index as ti  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-trace-search-mcp: missing dep: {e}\n"
        "Run: /kaizen:trace-search install\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-trace-search")


@mcp.tool()
async def trace_search(
    query: str,
    top_k: int = 10,
    src: str = "",
    sid: str = "",
    evt: str = "",
    since: str = "",
) -> list[dict]:
    """Semantic search over the kaizen trace SQLite index.

    query: natural-language description of what to find.
    top_k: max results.
    src/sid/evt: optional SQL pre-filters (exact match).
    since: duration (1h/30m/7d) or ISO timestamp.

    Returns list of {id, score, ts, src, evt, sid, tool, ms, data}.
    Score is cosine similarity in [0, 1]; higher = closer to query."""
    return ti.cmd_search(query, top_k=top_k, src=src, sid=sid, evt=evt,
                           since=since if since else None)


@mcp.tool()
async def trace_index_status() -> dict:
    """Index health: total events, model, dim, earliest/latest ts.
    Call this first to verify the index is built + current."""
    return ti.cmd_stats()


@mcp.tool()
async def trace_index_run(embed_data: bool = False, max_n: int = 0) -> dict:
    """Incremental index of new events. Skips already-indexed ones via
    content-hash dedup. Returns {indexed, total, model}.

    embed_data: if True, also embed safe data fields (model name, status,
    verdict). Default False keeps embeddings privacy-safe.
    max_n: cap new events this run (0 = unlimited)."""
    return ti.cmd_index(max_n=(max_n if max_n > 0 else None), embed_data=embed_data)


@mcp.tool()
async def trace_get(event_id: int) -> dict:
    """Fetch one indexed event by SQLite id (returned by trace_search)."""
    r = ti.cmd_get(event_id)
    return r if r else {"error": f"event id={event_id} not found"}


@mcp.tool()
async def trace_recent(limit: int = 20, src: str = "") -> list[dict]:
    """Latest N events by ts — no semantic ranking. Use for "what's
    happening right now" queries. Combine with src filter for narrowing."""
    if not ti.DB_PATH.exists():
        return []
    conn = ti.open_db(create=False)
    sql = "SELECT id, ts, src, evt, sid, tool, ms, data_json FROM trace_events"
    params: list = []
    if src:
        sql += " WHERE src = ?"
        params.append(src)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    out = []
    import json as _json
    for r in rows:
        out.append({
            "id": r["id"],
            "ts": r["ts"],
            "src": r["src"],
            "evt": r["evt"],
            "sid": r["sid"] or "",
            "tool": r["tool"] or "",
            "ms": r["ms"],
            "data": _json.loads(r["data_json"]) if r["data_json"] else {},
        })
    return out


if __name__ == "__main__":
    mcp.run()
