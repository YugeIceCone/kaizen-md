---
name: schema
description: Inspect declarative workflow schemas (v1.14.0+). Schemas live as yaml in `.kaizen/workflow/schemas/<name>/` (project, post-v1.22), `~/.claude/.kaizen/schemas/<name>/` (user), or the plugin's built-ins (minimalist, kaizen-default, spec-driven, onion-tdd-strict, debug-with-pdb). Pair with `/workflow schema=<name>` to run a schema-driven routine.
argument-hint: [list|show <name>|branches <name> <artifact>|validate <name>]
---

# kaizen schema

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/workflow_runner.py ${ARGUMENTS:-list}`
