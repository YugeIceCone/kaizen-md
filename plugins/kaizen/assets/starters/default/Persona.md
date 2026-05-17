---
created: {{today}}
updated: {{today}}
tags: [persona, system]
---

# Persona

Loaded at every session start. The plugin reads `## Mission` and
`## Directives` as instruction; `## Top Beliefs` is auto-populated
by `/kaizen:brain evolve` from your highest-confidence Notes.

---

## Mission

- **Name:** {{name}}
- **Timezone:** {{timezone}}
- **Languages:** {{languages}}
- **Role:** {{role}}

## Directives

_Hard rules and explicit preferences. Edit by hand. The plugin
never overwrites this section._

- **No deletions without explicit user authorization.** Read →
  analyze → dedup → migrate → consolidate BEFORE any `rm`. See
  [[Notes/pref-no-deletions]].
- **Brand new code is TDD.** Use `/kaizen:tdd` for any net-new
  component. RED → GREEN → REFACTOR. See
  [[Notes/pref-tdd-for-new-code]].

_(Add your own — Onion architecture? Coding-skills strict? Pair
discipline? File one per principle as a brain Note + link it here.)_

## Top Beliefs

_Auto-populated by `/kaizen:brain evolve` — ranks your highest-
confidence Notes from the `Notes/` directory. Empty until your
first evolve run (or your first capture builds confidence)._

## Evidence Log

_Append-only behavioural evidence. The capture flow writes here
when you say "remember this" or trigger the UserPromptSubmit hook._
