---
name: observe
description: "Unified observability across kaizen 6 data-stream layers (L1 stderr → L6 plugin state). Schema-driven (v1.9.0 data model). Verbs - layers | drill | stats."
argument-hint: [layers|query|stats|drill <sid>|snapshot [name]|compare <a> <b>|snapshots]
---

# kaizen observe

Cross-layer observability — 6 data streams from CC stderr up to plugin global state.

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/observe/observe.py ${ARGUMENTS:-layers}`

Programmatic access via the `kaizen-state` MCP server (read-only subset):

- `state_observe_layers()` — full 6-layer state dict
- `state_observe_drill(sid)` — cross-layer drill report for one session

Mutating ops (`snapshot`, `compare`) stay slash-only.

## Folded surface (formerly separate slashes)

Eight observability bins are reachable directly:

| Concern | Bin (direct) | Use case |
|---|---|---|
| Unified event log | `kaizen-trace` | tail / query / stats / event / search / index — was `/kaizen:trace` |
| Adoption + dead-feature | `kaizen-metrics` | session / lifetime / never-used / skips / noise — was `/kaizen:metrics` |
| Context-window state | `kaizen-context` | tokens used + zone + recommendation — was `/kaizen:context` |
| Statusline install + inspect | `kaizen-statusline` | one-line status bar — was `/kaizen:statusline` |
| Message inbox | `kaizen-inbox` | list / peek / drain / clear / stats — was `/kaizen:inbox` |
| Per-session chatlog | `kaizen-chatlog` | per-session markdown transcript — was `/kaizen:chatlog` |
| Error-locator + parse-validity | `kaizen-debug` | scan / parse / replay / lint / tail / smoke / check — was `/kaizen:debug` |
| Install state at-a-glance | `kaizen-status` | config + gate + backlog + workflow summary — was `/kaizen:status` |

All eight read runtime state across kaizen's six data-stream layers (L1 stderr → L6 plugin state). The observe umbrella above routes by layer + drill verb; the bins are the direct-invocation form.
