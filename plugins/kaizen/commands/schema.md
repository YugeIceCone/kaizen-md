---
name: schema
description: "Inspect declarative workflow schemas. Verbs - list | show <name> | branches <name> <id> | validate <name>. Pair with `/workflow schema=<name>` to run."
argument-hint: [list|show <name>|branches <name> <artifact>|validate <name>]
---

# kaizen schema

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workflow/workflow_runner.py ${ARGUMENTS:-list}`
