---
name: flow
description: Run the async pocketflow Node+Flow demo over the current workspace. 4-node pipeline (ReadBacklog → DetectPackages → GenerateDocs → WriteReport) with parallel fan-out via asyncio.gather. No LLM calls, no pip deps — vendors AsyncNode + AsyncFlow.
---

# kaizen flow demo (async, v1.4.0+)

Demonstrates the **async Node + Flow discipline** (single-responsibility steps, `prep_async` / `exec_async` / `post_async` phases, shared store between nodes, parallel fan-out) against a real artifact: this workspace's backlog + its package inventory.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/flow_demo.py "${ARGUMENTS:-.}"`

## The Flow

```
ReadBacklog → DetectPackages → GenerateDocs → WriteReport
                               ↑ fan-out via      ↑ terminal
                                 asyncio.gather
```

| Node | Responsibility |
|---|---|
| **ReadBacklog** | `prep`: resolve backlog path from `.kaizen.toml`. `exec`: load `backlog.json` off-loop via `asyncio.to_thread`. `post`: store size in shared. |
| **DetectPackages** | `prep`: get workspace root. `exec`: call `docs_gen.detect_packages` (scans for `Cargo.toml` / `package.json` / `go.mod` / `pyproject.toml`). `post`: store package list. |
| **GenerateDocs** | `prep`: pull packages + root. `exec`: **fan-out N packages → N parallel `asyncio.gather` tasks** — each calls `docs_gen.scan_package`. `post`: store records. |
| **WriteReport** | `prep`: gather sizes + records + per-node timings. `exec`: aggregate stats. `post`: print JSON summary. |

## Sample output (on shodan)

```json
{
  "workspace_root": "/home/cherry86/workspace/shodan",
  "backlog_items": 8,
  "packages_detected": 26,
  "packages_scanned": 26,
  "total_loc": 236702,
  "total_files": 1612,
  "by_language": { "rust": 26 },
  "top_5_by_loc": [
    { "name": "shodan", "loc": 118351 },
    { "name": "shodan-nodes", "loc": 48222 }
  ],
  "per_node_ms": {
    "ReadBacklog": 0,
    "DetectPackages": 6,
    "GenerateDocs": 1141
  }
}
```

24 crates scanned concurrently in ~1.1 s wall-clock. Sequential would be ~5–10× slower.

## Why this pattern?

Every LLM-driven feature in shodan (and any project following the bundled `kaizen:onion-ddd-workflow`) MUST decompose into:

1. **Node impls** — each step is a single-responsibility `Node` (or `AsyncNode`).
2. **A Flow** — composes the nodes, defines transitions, owns shared state.
3. **Explicit state machine** — shared store carries data between phases; no hidden globals.

The demo is the simplest non-trivial instance: 4 nodes, no LLM, no branching, with one fan-out. Real Modes (chat, plan, agent) add branching, LlmClient nodes, and retries — same skeleton.

## Zero pip dependencies

The script vendors a minimal `AsyncNode` + `AsyncFlow` (~40 LOC) whose shape mirrors PocketFlow's API exactly. If you'd rather use the upstream lib:

```bash
pip install --user --break-system-packages pocketflow
```

…then swap the two class definitions for `from pocketflow import AsyncNode, AsyncFlow`. Nothing else changes.

## Run from any shell

If `${CLAUDE_PLUGIN_ROOT}` is empty (you're outside Claude Code), source the kaizen env first:

```bash
source ~/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/kaizen/scripts/kaizen-env.sh
kaizen-flow .
```

`/kaizen:env install` adds that line to your `~/.bashrc` once.

## Inputs

```bash
/kaizen:flow                # cwd
/kaizen:flow /path/to/workspace
```

Pass a path or use cwd. The workspace doesn't need to be a kaizen-installed repo — the demo just needs at least one detectable package manifest.
