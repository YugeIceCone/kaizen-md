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
"""kaizen scrape-mcp — MCP server exposing semantic search over the kaizen
scrape index (web content scraped via SmartScraperGraph + embedded).

Sibling of knowledge_mcp.py / claude_docs_mcp.py / trace_mcp.py — same
FastMCP pattern, wraps `do_*` helpers in scrape_index.py.

Tools:
  scrape_search(query, top_k=8)     cosine search
  scrape_stats()                    {items, model, dim, last_indexed_ts}
  scrape_get(item_id)               full content of one indexed item
  scrape_list_recent(limit=20)      latest N items by updated_at
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from fastmcp import FastMCP
    import scrape_index as si  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-scrape-mcp: missing dep: {e}\n"
        "Run: /kaizen:scrape <url> (first run auto-installs deps via uv)\n"
    )
    sys.exit(1)


mcp = FastMCP("scrape")


@mcp.tool()
async def scrape_search(query: str, top_k: int = 8) -> list[dict]:
    """Semantic search over scraped web content.

    Returns list of {score, id, url, title, snippet, scraped_at}.
    Pass the returned `id` to scrape_get for full content."""
    return si.do_search(query, top_k=top_k)


@mcp.tool()
async def scrape_stats() -> dict:
    """Index meta — {items, model, dim, last_indexed_ts, size_bytes, db}."""
    return si.do_stats()


@mcp.tool()
async def scrape_get(item_id: int) -> dict:
    """Fetch one scraped item's full content by SQLite id."""
    r = si.do_get(item_id)
    return r if r else {"error": f"item id={item_id} not found"}


@mcp.tool()
async def scrape_list_recent(limit: int = 20) -> list[dict]:
    """Latest N scraped items by `scraped_at` — no semantic ranking.

    Use for "what's been scraped lately?" queries before deciding
    which sub-query to run."""
    return si.do_list(limit=limit)


if __name__ == "__main__":
    mcp.run()
