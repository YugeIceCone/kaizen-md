---
name: metrics
description: Rollup + never-used catalog + skip-detection + graveyard + MCP smoke-test over the kaizen trace log. Surfaces which skills/tools/MCP servers got used this session vs lifetime; which are available but never invoked; which skills should have been loaded but weren't (skip-detection); which artifacts are cold enough to archive (graveyard); whether every MCP server still imports (smoke). Use to self-correct after a session or audit the plugin's adoption. Subcommands - session | lifetime [--since DUR] | never-used [--kind skill|tool|mcp|bin] | top [--kind] [--n N] | skips | graveyard [--kind] [--stale-days N] | smoke --kind mcp | path
argument-hint: [session|lifetime|never-used|top|skips|graveyard|smoke|path]
---

# /kaizen:metrics

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/metrics.py $ARGUMENTS`
