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

## Adjacent diagnostic (folded surface)

For **MCP + hook registration drift** (different layer than this
file-system health check) use the `kaizen-surface` bin directly:

```bash
kaizen-surface list                 # 22 MCP servers + N hooks
kaizen-surface list --kind mcp      # only MCP
kaizen-surface list --kind hooks    # only hooks
kaizen-surface validate             # text report; exit 1 on errors
kaizen-surface validate --json      # array of Finding objects
```

`kaizen-surface` was previously surfaced as `/kaizen:surface`; that
slash was retired in the diagnostic-domain consolidation. The bin
stays — same checks, same flags.
