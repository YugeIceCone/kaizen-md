---
name: health
description: "Diagnostic health check - broken symlinks, missing scripts, schema mismatch, hook misconfig, stale backlog drift, missing pre-deletion belief. exit 1 on any error."
---

# kaizen health

Run a systematic diagnostic over the plugin's install state.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/health.sh`

Programmatic access via the `kaizen-state` MCP server:

- `state_health()` — `{ok, exit_code, output}`
- `state_health_summary()` — `{ok, green, warn, fail, result_line}` (compact form)
