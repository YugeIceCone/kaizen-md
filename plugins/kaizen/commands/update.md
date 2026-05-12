---
name: update
description: Single-command kaizen maintenance — `git pull` the marketplace, refresh Claude Code's plugin cache, auto-reload if anything changed, optionally prune old version slots. Subcommands: (none = pull+refresh+reload) | check | prune | path. Replaces the manual `cd marketplace + git pull + /kaizen:refresh-cache + /reload-plugins` dance.
argument-hint: [pull|check|prune|path]
---

# kaizen update

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/update.sh ${ARGUMENTS:-pull}`
