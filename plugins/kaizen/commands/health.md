---
name: health
description: Diagnostic health check for the kaizen plugin's install in this repo. Reports broken symlinks, missing scripts, schema mismatch, hook misconfiguration, stale backlog drift, missing pre-deletion belief. Read-only; exits 1 on any error, 0 otherwise.
---

# kaizen health

Run a systematic diagnostic over the plugin's install state.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/health.sh`

Programmatic access via the `kaizen-state` MCP server:

- `state_health()` — `{ok, exit_code, output}`
- `state_health_summary()` — `{ok, green, warn, fail, result_line}` (compact form)
