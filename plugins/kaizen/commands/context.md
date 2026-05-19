---
name: context
description: Report Claude Code's current context-window state — tokens used, percentage of limit, zone (green/yellow/red), and a recommendation. Uses CLAUDE_CONTEXT_TOKENS env or stdin JSON (statusline schema). Use to decide when to /compact, before a large refactor, or when the gate Check #12 fired a warning.
argument-hint: [show|json]
---

# kaizen context

Context-window state — tokens, pct, zone, recommendation.

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/util/context.py ${ARGUMENTS:-show}`

Programmatic access via the `kaizen-state` MCP server: `state_context()` returns `{tokens, limit, pct, zone, recommendation}` as a dict.
