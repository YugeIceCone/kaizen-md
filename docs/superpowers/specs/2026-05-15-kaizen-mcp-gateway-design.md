# Kaizen MCP Gateway — Design Spec (Subsystem A)

> Status: approved 2026-05-15. Subsystem A of a two-part consolidation;
> Subsystem B (slash-command consolidation) is a separate later spec.

## Problem

The kaizen plugin registers **19 MCP servers** in `.mcp.json` (plus
`brain_mcp.py` and `metrics_mcp.py`, built but unregistered). Across the
23 servers there are **142 tools**. Every registered server's full tool
list is injected into Claude's context every session — a large,
flat, hard-to-navigate surface. The driver for this work is
**tool-surface overload**: discoverability and context cost.

Constraints (hard priority, user-stated):

- **No loss of context or agentic ability.** Every tool callable today
  must remain callable, under its exact current name. The consolidation
  may reduce what is *listed* by default, but never what is *reachable*.

## Goal

One MCP server — a **gateway** — registered as the single `.mcp.json`
entry. It composes all 23 sub-servers in-process. Claude sees a small
curated surface by default (~15 tools); the full 142-tool catalog is
discoverable on demand via search and always fully callable.

## Why this is safe (the no-loss guarantee)

FastMCP v3's search transform **controls discovery, not access**. Per
the FastMCP docs: "The original tools are still callable; they're
hidden from the listing but remain fully functional." `list_tools()`
returns only the `always_visible` set + two synthetic tools; every
other tool stays callable by name. The no-loss property is therefore
**framework-provided**, not something this design has to engineer — and
it is additionally enforced by an explicit test (see Testing).

## Architecture

A new `skills/workflow/scripts/gateway.py` — a standalone `fastmcp`
(`>=3.0`) PEP-723 `uv run --script` script. It is the only MCP server
in `.mcp.json` (one entry: `kaizen`).

```python
from fastmcp import FastMCP
from fastmcp.server.transforms.search import RegexSearchTransform
import audit_mcp, backlog_mcp, loc_mcp, trace_mcp, ...   # the 23 modules

gw = FastMCP("kaizen")
for mod in (audit_mcp, backlog_mcp, loc_mcp, ...):
    gw.mount(mod.mcp)                       # NO namespace — see below
gw.add_transform(RegexSearchTransform(
    search_tool_name="kaizen_search_tools",
    call_tool_name="kaizen_call_tool",
))
# always_visible curated core marked via the transform's allowlist
gw.run()
```

### Mount without namespace

All 142 tool names are **globally unique** (verified — zero
collisions). The existing per-server convention already namespaces
them: `audit_*`, `loc_*`, `trace_*`, etc. `mount()` *with* a namespace
would double-prefix (`audit_audit_findings`). So mount is **bare** —
tool names stay byte-identical to what Claude knows today, which also
serves the no-loss priority.

### Components

| Component | Responsibility |
|---|---|
| `gateway.py` | Import + `mount()` the 23 sub-servers, apply the search transform, mark the curated core `always_visible`, run stdio. ~60–80 lines, no business logic. Wraps each import+mount in try/except so one broken server cannot kill the gateway; a startup self-check asserts the expected tool count. |
| 23 `*_mcp.py` sub-servers | Migrated from the `mcp` SDK to standalone `fastmcp`. Each stays a standalone, independently-testable module exporting a module-level `mcp` object. `.run()` stays `__main__`-guarded so importing is side-effect-free. |
| Curated core (~13 tools) | Hot-path read/search tools marked `always_visible`. Initial set: `loc_search`, `knowledge_search`, `onboard_search`, `trace_search`, `state_status`, `state_health_summary`, `workflow_status`, `backlog_list`, `iron_laws_check`, `audit_latest`, `metrics` rollup, `roadmap_next`, `drift_status`. Final set tuned in Phase 5. |
| `kaizen_search_tools` / `kaizen_call_tool` | Framework-synthetic (RegexSearchTransform). Search matches across tool names, descriptions, parameter names + descriptions, and returns full input schemas (no second round-trip). `call_tool` dispatches to any of the 142 tools. |

## Migration mechanics

Verified mechanical. Per sub-server file, the migration is **~2 lines**:

1. Swap `from mcp.server.fastmcp import FastMCP` → `from fastmcp import FastMCP`.
2. Swap `mcp>=1.0` → `fastmcp>=3.0` in the `# /// script` dependency block.

`@mcp.tool()` decorators, tool function bodies, and `.run()` are
**unchanged** — proven by `mcp_server.py` (the backlog server), which
already runs on standalone `fastmcp` with `@mcp.tool()`. All 23 servers
are pure tool servers: zero resources, zero prompts, zero
lifespan/middleware — nothing else to migrate.

One normalization: `mcp_server.py` is the lone non-PEP-723 server
(`#!/usr/bin/env python3` + a global `pip install fastmcp`). Migration
renames it `backlog_mcp.py` and gives it a proper `# /// script` block,
matching its 22 siblings.

## Dependency surface

The gateway imports all 23 modules at startup. Heavy dependencies
(`torch`, `sentence-transformers`, `playwright`, `numpy`) are **all
lazy-loaded** — verified: zero heavy module-top imports in any server.
So `import onboard_mcp` is cheap; torch only loads when an onboard tool
is actually *called*, inside the gateway process.

The gateway's `# /// script` block carries the **union** of all
sub-server dependencies: `fastmcp>=3.0`, `sentence-transformers>=2.7`,
`torch>=2.0` (CPU index), `playwright>=1.40`, `numpy>=1.24`,
`jsonschema>=4.0`, `pyyaml>=6.0`. This is a heavy venv on disk (~GB),
but it is built once and cached by uv, and `bootstrap.sh` already
pre-warms every `uv run --script` venv — the gateway's venv joins that
set automatically.

## Data flow

1. Claude Code reads `.mcp.json` → spawns one process: `uv run --script gateway.py`.
2. Gateway imports 23 modules, `mount()`s each, adds the search transform, runs stdio.
3. Claude's `list_tools` → ~13 `always_visible` core + `kaizen_search_tools` + `kaizen_call_tool`.
4. Long-tail use: `kaizen_search_tools("<regex>")` → matching tool defs *with full schemas* → `kaizen_call_tool("<name>", {...})` → gateway dispatches to the mounted tool → result.
5. Core tools: called directly, normal MCP flow.
6. Heavy tool (e.g. `onboard_search`): lazy-imports its deps into the gateway process on first call.

## Migration phasing (5 phases, each independently green)

1. **Gateway skeleton + pilot.** Create `gateway.py`; migrate 3 light
   servers (`iron_laws`, `manifests`, `drift`); mount them; prove
   `mount()` + `RegexSearchTransform` + `always_visible` work against
   real `fastmcp>=3.0`. `.mcp.json` gets the `kaizen` entry *alongside*
   the existing 19 (dual-run — no capability loss mid-migration). If
   the fastmcp API differs from the docs, this phase catches it — STOP
   and reassess rather than guessing.
2. **Migrate the remaining ~17** `mcp`-SDK servers (2-line change each)
   and mount them. Normalize `mcp_server.py` → `backlog_mcp.py`.
3. **Fold in `brain` + `metrics`** — migrate + mount the two
   unregistered servers (~20 newly-reachable tools).
4. **Flip `.mcp.json`** — remove the 19 individual entries, leave only
   `kaizen`. Collapse `plugin.json` permissions (~19 lines → 1:
   `Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/gateway.py:*)`).
5. **Curate + tune** — finalize the `always_visible` core set, tune the
   search transform, regenerate any affected references, CHANGELOG.

## Error handling

- Each sub-server `import` + `mount()` is wrapped in try/except: a
  broken sub-server logs loudly and degrades to "its tools
  unavailable," never kills the gateway.
- Startup self-check asserts the expected tool count is mounted — the
  no-loss invariant, enforced at boot.
- Tool-call failures propagate as normal MCP errors (unchanged from
  today's per-server behavior).

## Testing

- **Migrated sub-servers keep their existing tests.** Tool function
  bodies are unchanged, so the existing per-server tests must still
  pass post-migration. Each phase re-runs them.
- **New `tests/test_gateway.py`:** all 23 modules import + mount without
  error; `list_tools` returns exactly the curated core + the 2
  synthetic tools; `kaizen_search_tools` finds a known long-tail tool;
  `kaizen_call_tool` invokes one end-to-end; and an **explicit
  assertion that all 142 tools are reachable** — the no-loss guarantee
  as a regression test.
- `ci-gate.sh` (full static + unittest suite) green at every phase
  boundary.
- `metrics smoke --kind mcp` passes for the gateway.

## Out of scope

- Subsystem B (consolidating the 46 user-facing slash commands into
  logical umbrella commands) — separate spec, after this lands.
- Slash-command dedup (retiring commands that duplicate gateway tools)
  — folded into Subsystem B.
- Any change to tool *behavior* — this is pure composition + framework
  migration; tool semantics are untouched.
