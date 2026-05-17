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
never overwrites this section. This starter ships an opinionated
set — keep what fits, delete what doesn't._

- **Onion Architecture / DDD is mandatory for every structural change.**
  Inward-only dep arrows; ports as traits; bounded contexts get
  ast-grep boundary lints. Invoke `onion-ddd-workflow` skill BEFORE
  proposing changes. See [[Notes/pref-onion-architecture-strict]].

- **The 8 coding-skills principles apply to every code change.**
  DRY / KISS / SoC / SOLID / LoD / YAGNI / Boy-Scout / Convention.
  Pair the relevant `coding-skills:*` skill with the work; don't
  dilute the skill's Iron Laws. See [[Notes/pref-coding-skills-strict]].

- **No deletions without explicit authorization.** Read → analyze →
  dedup → migrate → consolidate. Never `rm` until the user has
  explicitly approved that specific deletion.
  See [[Notes/pref-no-deletions]].

- **Brand new code is TDD.** Use `/kaizen:tdd` for any net-new
  component. RED → GREEN → REFACTOR. See [[Notes/pref-tdd-for-new-code]].

- **Skills must be read in full — no exceptions.** When the `Skill`
  tool returns a SKILL.md body, read it end-to-end before applying
  any section, table, or example. The `description` is for routing
  only; the body carries the authoritative rules. No "I already
  know this skill" shortcut — skills evolve; re-read every time.

- **Orientation read first.** When the user opens with a list of
  files (plans, handoffs, architecture logs, `@<dir>/` references)
  for orientation, read them in full before proposing changes.
  See [[Notes/pref-orientation-pattern]].

- **Append session discoveries as you go; audit for memory promotion
  at end.** During multi-step sessions, capture non-obvious learnings
  continuously. At end-of-session, route project-scoped discoveries
  to auto-memory and cross-project discoveries to brain Notes.
  See [[Notes/pref-session-discovery-log]].

- **Use HARD-GATE blocks to codify durable rules.** When writing a
  rule that must be read in full, wrap each rule in
  `<HARD-GATE></HARD-GATE>` with imperative language + explicit
  applies-to / does-NOT-apply-to clauses + at least one
  counter-example. See [[Notes/pref-hard-gate-codification]].

## Top Beliefs

_Auto-populated by `/kaizen:brain evolve`. Empty until your first
evolve run promotes your highest-confidence Notes here._

## Evidence Log

_Append-only behavioural evidence. The capture flow writes here
when you say "remember this" or trigger the UserPromptSubmit hook._
