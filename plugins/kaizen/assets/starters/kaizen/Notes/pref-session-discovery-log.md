---
name: Append session discoveries continuously; audit for Remember promotion at end
description: During multi-step sessions, capture learnings + non-obvious findings as they happen (in TaskCreate / notes / handoff drafts). At end-of-session, audit the discovery log and promote cross-project bits to ~/.claude/brain/Notes/ (Remember tier). Project-specific bits stay in auto-memory.
type: belief
confidence: 0.8
tags: [preference, workflow, memory, learning-capture]
sources_count: 1
freshness: stable
created: 2026-05-14
updated: 2026-05-14
---

# Append session discoveries continuously; audit for Remember promotion at end

During a multi-step session, surface and CAPTURE every non-obvious
discovery as it happens. At end-of-session, audit the captured log
and route each entry to its correct memory tier:

  - **Project-specific** (gates, paths, naming, single-codebase quirks)
    → auto-memory at `~/.claude/projects/<slug>/memory/`
  - **Cross-project** (durable beliefs, patterns, world-facts, working-
    style preferences) → Remember tier at `~/.claude/brain/Notes/`

## Why

Discoveries decay fast. Capturing only at end-of-session means
mid-session insights get lost when the conversation moves on. The
post-hoc trace pass mostly works, but the *quality* of recall drops
sharply — vague paraphrase instead of the precise finding.

User stated as a process preference:

> "idea session discoveries append whatever you learn or figure out
> then at the end before or after you do what we just did now,
> check if we can use remember"

The "before or after" framing means the discovery-log + auto-memory
+ Remember-audit sequence is the durable shape — not a one-off.

## How to apply

1. **As-you-go capture.** During a session, when something
   non-obvious surfaces (a workaround, a pattern proven, a gap
   in tooling, a user correction):
   - If it's small + actionable: `TaskCreate` it OR append to a
     visible session-log artifact (handoff draft, notes scratch).
   - If it's a one-line rule: state it back to the user in the next
     turn so the conversation log captures it verbatim.

2. **End-of-session audit.** Before declaring done, scan the
   session for discoveries. For each one, apply the decision tree
   from global `CLAUDE.md ## Memory & Remember`:

   | Signal | Tier |
   |---|---|
   | Project-scoped correction / gotcha / decision | auto-memory |
   | User preference "always X" / "never Y" | Remember belief |
   | Working-style observation that generalizes | Remember observation |
   | Cross-project world-fact | Remember + project log |

3. **Write durables.** Project-scoped → write a file in the
   project's `memory/` dir + index in `MEMORY.md`. Cross-project
   → write a `pref-<slug>.md` in `~/.claude/brain/Notes/` (this
   file's shape) + optionally reference from `Persona.md
   ## Directives` if it's load-bearing enough to load every
   session.

4. **Don't duplicate.** Before writing, scan existing auto-memory
   + brain/Notes/ for a near-duplicate. Update it instead of
   creating a parallel entry.

## What counts as a "discovery"

- Tool / gate / hook surprises (workarounds, bypass syntax)
- Patterns proven across ≥3 modules / commits in one session
- Cross-cutting bugs or quirks the user didn't already know about
- Commit-message / PR / docs structure templates that worked
- User corrections (always promote unless trivially obvious)

NOT discoveries:
- Test counts, commit shas, LOC totals (those live in commit logs)
- Stage-by-stage progress (that's TaskCreate, not memory)
- Code-quality nits you would have applied anyway

## Edge cases

- If the session was short / single-step, skip the audit pass.
- If a discovery contradicts an existing belief, surface to the
  user before overwriting.
- Mid-session, if a single discovery is BIG (e.g. an architectural
  reframe), capture immediately to a Notes draft — don't wait.

## Evidence

- source: This session (2026-05-14, Phase 4 + O5 + gate fix)
  quote: "idea session discoveries append whatever you learn or
    figure out then at the end before or after you do what we
    just did now, check if we can use remember"
  date: 2026-05-14
