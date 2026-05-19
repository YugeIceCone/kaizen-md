---
name: intent
description: "Inspect or test the intent system - declarative phrase/event triggers that auto-suggest actions on UserPromptSubmit. Verbs - list | match | hits | path."
argument-hint: "[list | match \"<text>\" | suggest \"<text>\" | scan <session-id>]"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-intent:*)"]
---

# kaizen intent

Declarative phrase-and-event-pattern → action automation. The intent
system fires on every UserPromptSubmit (via `intent-userprompt.sh`
hook), matches the prompt against `skills/intent/domain/intents.yaml`
(31 rules as of this writing), and surfaces top-match suggestions as
`systemMessage`.

This slash command is the manual introspection surface — list /
match / suggest / scan — for debugging rules + ad-hoc lookup.

!`${CLAUDE_PLUGIN_ROOT}/bin/kaizen-intent ${ARGUMENTS:-list}`

## Subcommands

| Verb | Does |
|---|---|
| `list` (default) | Enumerate all registered intents (id + description + trigger kinds + confidence) |
| `match "<text>"` | Return ALL intents matching the text (sorted by confidence DESC) |
| `suggest "<text>"` | Return ONLY the top match (single highest-confidence intent) |
| `scan <session-id>` | Pull recent dxm events for the session + match against `event_pattern` triggers |

## When to use

- **`list`** — see what intent coverage exists; spot duplicates; audit
- **`match`** — debug "why didn't my prompt fire intent X?"
- **`suggest`** — what the UserPromptSubmit hook would emit for a given prompt
- **`scan`** — verify event-pattern triggers (e.g. "3+ Bash failures in 60s → suggest investigation") against a live session

## See also

- `skills/intent/domain/intents.yaml` — the rule catalog (31 rules, schema-validated)
- `hooks/claude/intent-userprompt.sh` — the live-fire hook
- `/kaizen:plugin-development intake` — pairs with intent for plugin-dev work
