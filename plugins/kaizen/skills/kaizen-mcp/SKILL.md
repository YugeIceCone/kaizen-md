---
name: kaizen-mcp
description: Catalog + dispatch hub for the kaizen-md plugin's MCP server fleet — 30+ per-domain `*_mcp.py` servers composed under one `gateway.py` FastMCP endpoint via SubServers/mount pattern. Tells you which MCP exposes what, how the gateway composes them, how to add a new MCP, when not to. Pairs with claude-hooks (lifecycle interactions) and discovery_mcp (federated search across all kaizen indexes). Triggers on "kaizen MCP", "add MCP server", "MCP fleet", "gateway SubServers", "FastMCP mount", "which MCP tool", "kaizen_search vs onboard_search", "discovery MCP", "MCP coverage audit".
---

# kaizen-mcp — MCP Server Fleet Catalog

## ⚠ Iron Law — read in full

Skip nothing. The gateway/SubServers composition + tool-name
discipline + RegexSearchTransform discovery layer only hold together
end-to-end. Adding an MCP without the `<domain>_*` tool-name
convention causes collisions; mounting without `__main__`-guarding
the run() causes side effects at import time.

## The architecture

```
┌─────────────────────────────────────────────────────────────┐
│  .mcp.json  →  registers ONE entry: `kaizen` → gateway.py   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │     gateway.py         │
          │  (FastMCP + transform) │
          └────────┬───────────────┘
                   │  imports + mounts (no namespace)
                   ▼
   ┌────────────────────────────────────────────────┐
   │  30+ *_mcp.py modules                          │
   │  Each: `mcp = FastMCP(...)` + `@mcp.tool()`s   │
   │  Each: `__main__`-guarded run() (import-safe)  │
   │  Each: tools named `<domain>_*` (no collision) │
   └────────────────────────────────────────────────┘
```

**Tool discovery** is controlled by `RegexSearchTransform`:
- `always_visible` core (curated list of high-traffic tools)
- Two synthetic tools: `kaizen_search_tools` (regex search the surface),
  `kaizen_call_tool` (invoke by name)
- Every other tool stays CALLABLE but isn't in default `list_tools()`
  output — the search transform controls DISCOVERY, not access.

## The fleet (29 mounted MCPs as of last gateway update)

| MCP | Domain | Key tools |
|---|---|---|
| `iron_laws_mcp` | Iron-laws registry + checks | iron_laws_check, iron_laws_list |
| `manifests_mcp` | plugin.json / .mcp.json inspection | manifests_get, manifests_validate |
| `drift_mcp` | Brain/auto-load drift detection | drift_check |
| `brain_mcp` | Second Brain (capture / search / promote / audit / evolve) | brain_capture, brain_search, brain_promote_*, brain_audit, brain_evolve, brain_index_build, brain_index_stats |
| `metrics_mcp` | Session + lifetime metrics rollup | metrics_session, metrics_lifetime |
| `backlog_mcp` | Backlog CRUD | list_items, add_item, tick_item |
| `browser_mcp` | Playwright browser automation | (loaded only if installed) |
| `trace_mcp` | Trace event search | trace_search |
| `knowledge_mcp` | Knowledge corpus semantic search | knowledge_search |
| `onboard_mcp` | Codebase semantic onboard | onboard_search |
| `claude_docs_mcp` | Claude docs semantic search | claude_docs_search |
| `scrape_mcp` | Web scrape + index | scrape_url, scrape_search |
| `discovery_mcp` | Federated kaizen_search across 4 indexes | kaizen_search, discovery_search, pick_corpus |
| `state_mcp` | Workflow state inspection | state_status, state_health_summary |
| `lint_mcp` | Lint + auto-fix dispatch | auto_fix_lint |
| `workflow_mcp` | Workflow orchestration | workflow_status |
| `loc_mcp` | Lines-of-code symbol search | loc_search |
| `loop_mcp` | Loop ledger (ralph-loop state) | loop_state |
| `shim_mcp` | Shim-and-sweep pattern helpers | shim_* |
| `rerank_mcp` | Cross-encoder rerank pipeline | rerank |
| `audit_mcp` | Audit-latest reader | audit_latest |
| `roadmap_mcp` | Roadmap status | roadmap_status |
| `gatekeeper_mcp` | Gatekeeper check | gatekeeper_check |
| `dxm_mcp` | Live DXM event stream | dxm_* |
| `intent_mcp` | Intent automation rules | intent_* |
| `ollama_mcp` | Local Ollama bridge | ollama_* |
| `context_mcp` | Agent context query | context_* |
| `quality_mcp` | Quality axes aggregator | quality_* |
| `detect_stack_mcp` | Stack detection | detect_stack |
| `symbol_search_mcp` | Symbol + exact-line search | symbol_search |
| `handoff_mcp` | Handoff get/list | handoff_get, handoff_list |
| `webfetch_mcp` | WebFetch semantic capture | webfetch_search |

## Adding a new MCP server (checklist)

1. **File**: `plugins/kaizen/skills/workflow/scripts/<name>_mcp.py`
2. **Shape**:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""<Domain> MCP server — exposes <verbs> as MCP tools."""

from fastmcp import FastMCP

mcp = FastMCP("kaizen-<domain>")


@mcp.tool()
async def <domain>_<verb>(arg1: str, arg2: int = 10) -> dict:
    """One-line summary that an LLM will read to decide to call this."""
    return {...}


if __name__ == "__main__":  # __main__-guarded — safe to import
    mcp.run()
```

3. **Tool-name convention**: every tool MUST start with `<domain>_`.
   The gateway mounts WITHOUT namespace so this prefix is the only
   collision-avoidance mechanism.
4. **Register in `gateway.py::SUBSERVERS`**: add the
   `("<short-name>", "<module>_mcp")` tuple.
5. **Add permissions**: `plugin.json::permissions.allow` gets
   `Bash(python3 ${...}/scripts/<name>_mcp.py:*)` (or rely on the
   `*.py:*` wildcard).
6. **Add a test**: `tests/test_<name>_mcp.py` — at minimum, verifies
   the module imports cleanly + lists its tools.
7. **Add coverage**: `kaizen-mcp-coverage` will validate the MCP has
   a paired test.

## When NOT to add a new MCP

- **The work fits a sibling MCP** — extend that one (add a tool to its
  `mcp.tool()` set) instead of creating a new module. KISS + YAGNI.
- **The work is one-off / single-script** — make it a CLI (`bin/kaizen-<verb>`)
  instead. MCP overhead isn't justified.
- **The work is hot-path** — Python startup cost of MCP add latency
  to every call. Hot-path work should be inline in a hook handler.

## Audit + observability

- `kaizen-mcp-coverage` — every `*_mcp.py` should have a paired
  `tests/test_*_mcp.py`.
- `kaizen-mcp-trace-coverage` — every registered MCP should emit at
  least one trace event when its tools are called.
- `gateway.py [validate]` — surfaces import errors / collision warnings.
- `surface.py validate` — orphan-MCP detection (file on disk not in
  SUBSERVERS).

## Pairing with siblings

| Sibling | Relationship |
|---|---|
| `discovery_mcp` (kaizen_search) | Routes a generic search across the 4 corpora (onboard / knowledge / claude_docs / scrape). kaizen-mcp catalogs it; discovery_mcp is the meta-search tool. |
| `claude-hooks` | Hooks fire in-process; MCPs are out-of-process via stdio. Different lifecycle. |
| `gatekeeper` | Pre-commit gate runs MCP coverage / trace coverage as sub-gates. |
| `iron-laws` | `mcp-tool-naming-convention` rule (enforced via gatekeeper). |

## Triggers (when to load this skill)

- About to add a new MCP server
- Confused about which MCP exposes a tool
- Auditing the MCP fleet (orphans, gaps, trace coverage)
- Understanding the gateway SubServers / RegexSearchTransform pattern
- Choosing between MCP tool vs CLI vs hook handler

## DON'T load when

- Just CALLING an existing MCP tool (already documented in its description)
- Authoring hooks (load `Skill(kaizen-hook)` instead)
- Building bin wrappers only (load `Skill(plugin-development)` instead)
