---
name: inbox
description: Manage the kaizen message inbox — captures every user message via UserPromptSubmit, surfaces pending messages on the next PostToolUse boundary so Claude sees user input mid-sequence without waiting for the whole tool chain to finish. Subcommands: list | peek | drain | clear | stats. Location: ~/.claude/.kaizen/inbox/.
argument-hint: [list|peek|drain|clear|stats]
---

# kaizen inbox

User-message inbox — captures every UserPromptSubmit; Claude sees them on each PostToolUse boundary.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/inbox.py ${ARGUMENTS:-stats}`

Programmatic access via the `kaizen-state` MCP server (read-only subset):

- `state_inbox_peek(n=5)` — next N pending without marking drained
- `state_inbox_list(pending_only=True)` — full list

Mutating ops (`drain`, `clear`) stay slash-only.
