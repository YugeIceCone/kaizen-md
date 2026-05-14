---
name: metrics
description: Rollup + never-used catalog + skip-detection over the kaizen trace log. Surfaces which skills/tools/MCP servers got used this session vs lifetime; which are available but never invoked; which skills should have been loaded but weren't (skip-detection). Use to self-correct after a session or audit the plugin's adoption. Subcommands - session | lifetime [--since DUR] | never-used [--kind skill|tool|mcp|bin] | top [--kind] [--n N] | skips | path
argument-hint: [session|lifetime|never-used|top|skips|path]
---

# /kaizen:metrics

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/metrics.py ${ARGUMENTS:-lifetime --since 7d}`
