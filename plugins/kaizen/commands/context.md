---
name: context
description: "CC context-window state report - tokens used, percentage, zone (green/yellow/red), recommendation. Uses CLAUDE_CONTEXT_TOKENS env or statusline-shape stdin."
argument-hint: [show|json]
---

# kaizen context

Context-window state — tokens, pct, zone, recommendation.

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/util/context.py ${ARGUMENTS:-show}`

Programmatic access via the `kaizen-state` MCP server: `state_context()` returns `{tokens, limit, pct, zone, recommendation}` as a dict.
