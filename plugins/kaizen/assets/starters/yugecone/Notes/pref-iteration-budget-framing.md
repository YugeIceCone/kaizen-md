---
name: Iteration budget framing for autonomous loops
description: User declares loop budget upfront as "N iterations, 1 phase = 1 iteration baseline, extend on demand." Hard cap stated explicitly; agent requests extensions only when needed.
type: belief
confidence: 0.9
tags: [preference, workflow, ralph-loop, loop, autonomous, budget]
sources_count: 1
freshness: stable
created: 2026-05-11
updated: 2026-05-11
---

# Iteration budget framing for autonomous loops

When kicking off a multi-iteration autonomous loop, user declares the
budget upfront with a phase-mapping rule. Pattern:

> **[15:31] User:** continue 1 Phase is 1 iteration, extend by 1
> iteration if you need more to complete the plan.

> **[15:44] User:** continue run until done 20 its

Two-step framing:
1. **Phase-to-iteration mapping**: baseline 1 phase = 1 iteration.
2. **Hard cap**: stated as "N its" (e.g. "20 its") — explicit ceiling.
3. **Extension rule**: agent may extend by 1 iteration when needed,
   but should not silently consume the budget on unrelated work.

## How to apply

- When user says "1 Phase is 1 iteration", treat each phase document
  in the plan as one ralph iteration. Don't pack two phases into one
  iteration to "save budget" — that defeats the verification cadence.
- When user says "N its", that's the **hard ceiling**, not a target.
  Land work in fewer iterations when possible.
- If complete before the cap, **stop**. The dual-stream upgrade hit
  16/20 with work feature-complete; the remaining 4 were left unused
  rather than padded with speculative improvements.
- If approaching the cap and work remains, **summarize state + flag
  the budget hit** rather than racing through final iterations with
  reduced verification quality.

## Why

- Predictable cost (each iteration has a known token/compute footprint).
- Forces phase-level commits at iteration boundaries (clean rollback
  points).
- Prevents scope creep: agent can't quietly turn a 5-iter task into a
  15-iter task without re-asking.

## Evidence

- source: Journal/2026-05-11.md
  quote: "continue 1 Phase is 1 iteration, extend by 1 iteration if you need more to complete the plan."
  date: 2026-05-11
- source: Journal/2026-05-11.md
  quote: "continue run until done 20 its"
  date: 2026-05-11
