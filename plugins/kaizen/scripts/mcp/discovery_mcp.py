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
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — relocated modules + legacy helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "handlers"))

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


def _fetch_ollama_models_with_caps() -> list[dict]:
    """Query Ollama for every local model + per-model capabilities.
    Returns [{name, capabilities, dim}]. Raises ConnectionError when
    Ollama is unreachable so the caller can degrade gracefully.

    capabilities source: Ollama's /api/show response includes a
    `capabilities` list (e.g. ["embedding"] or ["completion"]).
    dim source: model_info's `*.embedding_length` for embedding models.
    """
    import os
    from urllib import error, request

    host = (os.environ.get("KAIZEN_OLLAMA_HOST")
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434").rstrip("/")
    if "://" not in host:
        host = f"http://{host}"

    try:
        with request.urlopen(f"{host}/api/tags", timeout=2) as r:
            tags = json.loads(r.read())
    except (error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(f"Ollama unreachable at {host}: {exc}")

    out: list[dict] = []
    for m in tags.get("models", []) or []:
        name = m.get("name") or m.get("model") or ""
        if not name:
            continue
        caps: list[str] = []
        dim: int | None = None
        try:
            data = json.dumps({"name": name}).encode()
            req = request.Request(
                f"{host}/api/show", data=data,
                headers={"Content-Type": "application/json"},
            )
            with request.urlopen(req, timeout=2) as r:
                info = json.loads(r.read())
            caps = info.get("capabilities") or []
            mi = info.get("model_info") or {}
            # Ollama stores embedding dim under `<family>.embedding_length`
            for k, v in mi.items():
                if k.endswith(".embedding_length") and isinstance(v, int):
                    dim = v
                    break
        except (error.URLError, TimeoutError, OSError, ValueError):
            # Per-model failures don't poison the whole list.
            pass
        out.append({"name": name, "capabilities": caps, "dim": dim})
    return out


def _list_available_embed_models() -> list[dict]:
    """Locally-available embedding-capable models. Empty when Ollama
    is down — the discovery surface still works (sentence-transformers
    cache is the fallback embedding backend for codebase / knowledge)."""
    try:
        models = _fetch_ollama_models_with_caps()
    except ConnectionError:
        return []
    return [m for m in models if "embedding" in (m.get("capabilities") or [])]


@mcp.tool()
async def discovery_list_embed_models() -> list[dict]:
    """List locally-available embedding-capable models (Ollama-side).

    Returns [{name, capabilities, dim}]. Empty when Ollama is
    unreachable — discovery surfaces that use sentence-transformers
    (codebase / knowledge) still work without Ollama.

    Use before deciding which surface to re-index against a different
    backend, or when comparing dim/cost tradeoffs across local
    embedding options.
    """
    return _list_available_embed_models()


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


# ─── Phase 4.B: unified kaizen_search with auto-corpus routing ──────


# First-match-wins regex routing rules. Order matters: more specific
# patterns first. Each rule maps (pattern → corpus name).
_CORPUS_ROUTING_RULES: list[tuple[str, str]] = [
    # Code-shape patterns → symbol search
    (r"\b(def|class|fn|func|function|method)\b", "symbol-search"),
    # Brain-note ref shape (pref-X / Notes/X)
    (r"(^|\b)(pref-|Notes/|brain[/ ])", "brain"),
    # Error / exception shape → kaizen-trace
    (r"\b(error|exception|traceback|stack ?trace|fail(ed|ure)?)\b",
     "trace"),
    # URL → scrape store
    (r"https?://", "scrape"),
    # Claude-docs cues
    (r"\b(claude code|anthropic|claude api|hooks?|MCP)\b", "claude-docs"),
]


def pick_corpus(query: str, corpus: str = "auto") -> str:
    """Resolve a corpus name from explicit hint or query auto-routing.

    Args:
      query: the search text (used only when corpus='auto').
      corpus: 'auto' (pattern-route), 'all' (fan-out), or an explicit
              corpus name (passes through unchanged).

    Returns the resolved corpus name. Falls through to 'all' when
    'auto' finds no rule match — federates across surfaces rather
    than returning nothing.
    """
    if corpus and corpus != "auto":
        return corpus
    import re
    q = (query or "").lower()
    for pattern, name in _CORPUS_ROUTING_RULES:
        if re.search(pattern, q, re.I):
            return name
    return "all"


@mcp.tool()
async def kaizen_search(
    query: str,
    corpus: str = "auto",
    top_k: int = 10,
) -> dict[str, Any]:
    """Unified semantic search across kaizen's 7 indexes.

    Args:
      query:  free-text search string.
      corpus: routing hint:
              - 'auto' (default) — pattern-route by query shape
              - 'all'  — federate across all indexes
              - explicit name (codebase / knowledge / claude-docs /
                scrape / brain / trace / symbol-search) — single
                surface, no auto-routing.
      top_k:  per-surface result cap.

    Returns:
      {"corpus": <resolved-name>, "results": {<surface>: hits | {error}}}

    Composes existing discovery_search for the 4 federated surfaces;
    direct passthrough for symbol-search + brain + trace.
    """
    resolved = pick_corpus(query, corpus)
    out: dict[str, Any] = {"corpus": resolved, "results": {}}
    # 'all' → federated discovery_search (4 surfaces) — plus a future
    # extension for brain / trace / symbol-search direct calls.
    if resolved == "all":
        out["results"] = await discovery_search(query, top_k_per=top_k)
        return out
    # Single-surface route. We don't yet wire brain / trace / symbol-search
    # direct calls here — those have their own MCP tools that the agent
    # can call. We surface a pointer so the agent knows where to go.
    if resolved in ("codebase", "knowledge", "claude-docs", "scrape"):
        out["results"] = await discovery_search(
            query, surfaces=[resolved], top_k_per=top_k)
        return out
    out["results"] = {
        resolved: {
            "hint": (f"Use mcp__kaizen__{resolved.replace('-', '_')}_search "
                     f"directly for richer per-surface filters.")
        }
    }
    return out


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
