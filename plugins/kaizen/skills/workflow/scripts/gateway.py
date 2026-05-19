#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
#     "jsonschema>=4.0",
# ]
# ///
"""kaizen MCP gateway — the single MCP entry point.

Composes the plugin's per-domain MCP sub-servers into one FastMCP
server. Each sub-server is imported as a plain Python module (its
`.run()` is __main__-guarded, so importing is side-effect-free) and
mounted WITHOUT a namespace — every tool name is already globally
unique via the per-server `<domain>_*` convention, so bare mount keeps
tool names byte-identical to the pre-gateway world.

A RegexSearchTransform restricts the default `list_tools()` output to a
curated `always_visible` core plus two synthetic tools
(`kaizen_search_tools` / `kaizen_call_tool`); every other tool stays
fully callable — the search transform controls discovery, not access.

API note (verified against fastmcp>=3.0 in Phase 1's spike):
`FastMCP.mount(server)` composes live; `RegexSearchTransform` takes
`always_visible: list[str]`, `search_tool_name`, `call_tool_name` as
constructor kwargs.

Phase 1: pilots only (iron_laws, manifests, drift). Later phases extend
SUBSERVERS into the full 21-server list.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# MIGRATION BRIDGE — moved MCPs in scripts/brain/, scripts/indexers/, scripts/handlers/
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "handlers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "mcp"))

from fastmcp import FastMCP

# (name, module-import-name) for every sub-server to mount. Extended in
# later phases. `name` is the short domain label used in diagnostics.
SUBSERVERS: list[tuple[str, str]] = [
    # Phase 1 pilots
    ("iron_laws", "iron_laws_mcp"),
    ("manifests", "manifests_mcp"),
    ("drift", "drift_mcp"),
    # Phase 2 — remaining servers
    ("brain", "brain_mcp"),
    ("metrics", "metrics_mcp"),
    ("backlog", "backlog_mcp"),
    ("browser", "browser_mcp"),
    ("trace", "trace_mcp"),
    ("knowledge", "knowledge_mcp"),
    ("onboard", "onboard_mcp"),
    ("claude_docs", "claude_docs_mcp"),
    ("scrape", "scrape_mcp"),
    ("discovery", "discovery_mcp"),
    ("state", "state_mcp"),
    ("lint", "lint_mcp"),
    ("workflow", "workflow_mcp"),
    ("loc", "loc_mcp"),
    ("loop", "loop_mcp"),
    ("shim", "shim_mcp"),
    ("rerank", "rerank_mcp"),
    ("audit", "audit_mcp"),
    ("roadmap", "roadmap_mcp"),
    ("gatekeeper", "gatekeeper_mcp"),
    # Phase 3 — live-state + intent automation
    ("dxm", "dxm_mcp"),
    ("intent", "intent_mcp"),
    # Phase 4 — local LLM bridge
    ("ollama", "ollama_mcp"),
    # Phase 5 — agent-context query
    ("context", "context_mcp"),
    # Phase 6 — quality axes (frontmatter / coverage / name-quality /
    #           schema-coverage / slash-collision)
    ("quality", "quality_mcp"),
    # Phase 7 — stack detection
    ("detect_stack", "detect_stack_mcp"),
    # Phase 8 — handoff read-mostly queries
    ("handoff", "handoff_mcp"),
    # Phase 9 — config lookup
    ("config", "config_mcp"),
    # Phase 10 — WebFetch recall + policy + dedup
    ("webfetch", "webfetch_mcp"),
    # Phase 11 — symbol search with exact line ranges (Phase 3/9 of arc)
    ("symbol_search", "symbol_search_mcp"),
]

gw = FastMCP("kaizen")
MOUNTED: list[tuple[str, object]] = []
MOUNT_ERRORS: list[str] = []

for name, modname in SUBSERVERS:
    try:
        mod = __import__(modname)
        gw.mount(mod.mcp)
        MOUNTED.append((name, mod))
    except BaseException as exc:  # one broken server must not kill the gateway
        MOUNT_ERRORS.append(f"{name}: {exc}")

# Curated core — the hot-path read/search tools kept always-visible in
# the default tool list. Everything else is reachable via the search
# transform's kaizen_search_tools / kaizen_call_tool synthetic tools.
# Discovery is curated; access is not — every tool stays fully callable.
CURATED_CORE: list[str] = [
    # search — find code / docs / events / notes (4)
    "loc_search", "knowledge_search", "onboard_search", "trace_search",
    # state inspection — what's the current workflow / health (3)
    "state_status", "state_health_summary", "workflow_status",
    # backlog + audit (2)
    "list_items", "audit_latest",
    # gates — the "is this OK to ship" surface (3)
    "iron_laws_check", "gatekeeper_check", "auto_fix_lint",
    # observability (1)
    "metrics_session",
    # Dropped from earlier core: `roadmap_next` (low-traffic),
    # `drift_status` (low-traffic) — both reachable via kaizen_search_tools.
]

SEARCH_TRANSFORM_APPLIED = False
try:
    from fastmcp.server.transforms.search import RegexSearchTransform
    gw.add_transform(RegexSearchTransform(
        search_tool_name="kaizen_search_tools",
        call_tool_name="kaizen_call_tool",
        always_visible=CURATED_CORE,
    ))
    SEARCH_TRANSFORM_APPLIED = True
except BaseException as exc:  # never block the gateway on a transform issue
    MOUNT_ERRORS.append(f"search-transform: {exc}")

if __name__ == "__main__":
    if MOUNT_ERRORS:
        for e in MOUNT_ERRORS:
            print(f"[gateway] mount error: {e}", file=sys.stderr)
    gw.run()
