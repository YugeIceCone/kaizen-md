#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen discovery-mcp — cross-surface federated search aggregator.

Sibling-meta of onboard_mcp / knowledge_mcp / claude_docs_mcp /
scrape_mcp. Each per-surface MCP already exists and ships its own
search / stats / get tools; this aggregator adds the value those
don't have: **one call, multiple surfaces, parallel reads, grouped
results**.

Use when you want to query across "all kaizen indexes" without
chaining 4 separate MCP tool calls. Per-surface failures (missing DB,
ollama unavailable, etc.) degrade gracefully — the other surfaces
still return.

Tools:
  discovery_search(query, surfaces=[...], top_k_per=4)
                                          federated cosine; one call → grouped
  discovery_stats(surfaces=[...])         multi-surface stats in one shot
  discovery_list_surfaces()               metadata catalog (slash, db, model)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(
        f"kaizen-discovery-mcp: missing dep: {e}\n"
        "Run via gateway.py (uv auto-installs fastmcp on first invoke)\n"
    )
    sys.exit(1)


mcp = FastMCP("discovery")


# Per-surface catalog — single source of truth for the 4 indexes.
# Loaded lazily inside _do_*_surface so an absent index doesn't break
# the aggregator's import (e.g., a fresh install with no scrape index).
SURFACES: dict[str, dict[str, str]] = {
    "codebase": {
        "slash": "/kaizen:onboard",
        "index_module": "onboard_index",
        "desc": "Source files in this repo (extension allowlist, comments stripped)",
    },
    "knowledge": {
        "slash": "/kaizen:knowledge",
        "index_module": "knowledge_index",
        "desc": "Brain notes, plans, backlog, schemas, persona beliefs",
    },
    "claude-docs": {
        "slash": "/kaizen:claude-docs",
        "index_module": "claude_docs_index",
        "desc": "Local Claude API/Code/SDK docs mirror",
    },
    "scrape": {
        "slash": "/kaizen:scrape",
        "index_module": "scrape_index",
        "desc": "Pages scraped via PocketFlow + ScrapeGraphAI",
    },
}


def _do_search_surface(surface: str, query: str, top_k: int) -> list[dict]:
    """Dispatch a search to one surface. Raises on failure; the
    aggregator wraps the exception per-surface so other surfaces
    survive."""
    if surface not in SURFACES:
        raise ValueError(f"unknown surface: {surface}")
    mod = __import__(SURFACES[surface]["index_module"])
    return mod.do_search(query, top_k=top_k)


def _do_stats_surface(surface: str) -> dict:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface: {surface}")
    mod = __import__(SURFACES[surface]["index_module"])
    return mod.do_stats()


def _resolved_surfaces(picked: list[str] | None) -> list[str]:
    """None / empty → all known surfaces; otherwise honor the pick."""
    if not picked:
        return list(SURFACES.keys())
    return list(picked)


@mcp.tool()
async def discovery_list_surfaces() -> list[dict]:
    """List the 4 known discovery surfaces with their underlying slash
    and a one-line description. Read this first to plan a federated
    search/stats call.

    Returns: [{name, slash, desc}, ...]
    """
    return [
        {"name": name, "slash": meta["slash"], "desc": meta["desc"]}
        for name, meta in SURFACES.items()
    ]


@mcp.tool()
async def discovery_search(
    query: str,
    surfaces: list[str] | None = None,
    top_k_per: int = 4,
) -> dict[str, Any]:
    """Federated semantic search across one or more kaizen indexes.

    One call hits each picked surface in parallel; results are grouped
    by surface so the caller can compare hits across domains without
    chaining 4 separate MCP tool calls. Per-surface failures degrade
    gracefully (other surfaces still return; the failure surfaces as
    {"error": "..."} for that key).

    Args:
        query: search text.
        surfaces: subset of ["codebase","knowledge","claude-docs","scrape"];
                   omit to query all four.
        top_k_per: max hits returned per surface (default 4 — keeps the
                   aggregated payload compact).

    Returns:
        {<surface-name>: [hit, ...] | {"error": "..."}}
    """
    picked = _resolved_surfaces(surfaces)

    def _run(name: str) -> tuple[str, Any]:
        try:
            return name, _do_search_surface(name, query, top_k_per)
        except Exception as exc:  # noqa: BLE001 — per-surface isolation
            return name, {"error": str(exc)}

    results = await asyncio.gather(
        *(asyncio.to_thread(_run, n) for n in picked)
    )
    return {name: result for name, result in results}


@mcp.tool()
async def discovery_stats(
    surfaces: list[str] | None = None,
) -> dict[str, Any]:
    """Per-surface index stats in one shot. Same federated pattern as
    discovery_search — picked surfaces run in parallel, failures
    surface as {"error": "..."}.

    Args:
        surfaces: subset of the 4 known surfaces; omit for all.

    Returns:
        {<surface-name>: <stats dict> | {"error": "..."}}
    """
    picked = _resolved_surfaces(surfaces)

    def _run(name: str) -> tuple[str, Any]:
        try:
            return name, _do_stats_surface(name)
        except Exception as exc:  # noqa: BLE001
            return name, {"error": str(exc)}

    results = await asyncio.gather(
        *(asyncio.to_thread(_run, n) for n in picked)
    )
    return {name: result for name, result in results}


if __name__ == "__main__":
    mcp.run()
