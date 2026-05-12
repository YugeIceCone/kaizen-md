---
name: observe
description: Unified observability across kaizen's 6 data-stream layers (L1 stderr → L6 plugin state). Schema-driven (uses v1.9.0 dataclasses), with dynamic queries (live filtering) and deterministic snapshots (SHA1-content-keyed captures). Subcommands: layers | query | stats | drill <sid> | snapshot | compare | snapshots. Drill is the automated debugging recipe.
argument-hint: [layers|query|stats|drill <sid>|snapshot [name]|compare <a> <b>|snapshots]
---

# kaizen observe

Cross-layer observability — 6 data streams from CC stderr up to plugin global state.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/observe.py ${ARGUMENTS:-layers}`

Programmatic access via the `kaizen-state` MCP server (read-only subset):

- `state_observe_layers()` — full 6-layer state dict
- `state_observe_drill(sid)` — cross-layer drill report for one session

Mutating ops (`snapshot`, `compare`) stay slash-only.
