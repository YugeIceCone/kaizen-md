---
name: status
description: Show the kaizen setup for this repo at a glance — config, gate state, backlog summary, active workflow-routing routine, backup count, migration candidates.
---

# kaizen status

Quick health-check / summary for this repo.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/status.sh`

Programmatic access (no slash command): `state_status()` on the `kaizen-state` MCP server returns the same raw output as a string.
