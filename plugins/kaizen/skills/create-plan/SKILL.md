---
name: plan-creating
description: Creates phased, agent-reusable implementation plans for multi-step or risky work. Use when the user asks to "create a plan", "plan this out", "make a plan", "draft an implementation plan", "phase this work", "plan the migration", "plan the refactor", or when sequence, rollback, or blast radius needs explicit documentation. Plans are written so a fresh agent or subagent can resume execution at any phase without back-channel context.
metadata:
  version: "1.2"
---

# Plan Creating

Creates a phased, agent-reusable implementation plan for multi-step or risky work. Plans produced here are durable artifacts: another agent (subagent, fresh session, or pair-execution worker) can open the file and resume execution at any phase without re-deriving context.

If a good approved plan already exists, use **plan-executing** instead. If only one task or phase needs decomposition, use **tasks-creating**.

**Before writing tasks that call an external library:** confirm the
API shape against Context7 (`resolve-library-id` → `query-docs`). A
plan step that shows the wrong method signature or import path is a
plan failure — the executing agent will copy it verbatim.

## When To Use

Trigger this skill when any of the following apply:

- the work spans multiple files or modules
- the order of operations matters
- rollback is non-trivial
- the user asks for a plan first, or for "phases" / "milestones" / "checkpoints"
- a refactor, migration, or risky fix needs explicit verification gates
- the plan will be handed to a subagent, scheduled run, or future session

## Inputs

Confirm before drafting; gather what is missing in **Context Gathering** below:

- the user request or problem statement, in their words
- explored code paths, tests, and constraints
- research findings that affect the plan (API versions, breaking changes, etc.)
- the project's verification commands (tests, lint, typecheck, build)

If the codebase shape is still unclear, run **codebase-exploring** or **change-analyzing** first. Do not draft a plan on guessed structure.

## Context Gathering

A plan is only as reliable as the context that grounds it. Skip ahead to drafting only if every item below is already settled.

1. **Read the request literally.** Pull goals and constraints directly from the user's words. Note implicit ones too (e.g. "without breaking the API" implies a public-API invariant).
2. **Map the affected surface.** Open the files, callers, and configs the work touches. Use **codebase-exploring** for unfamiliar areas, **structural-code-searching** for symbol-level mapping, **change-analyzing** for blast radius.
3. **Surface constraints and invariants.** Performance budgets, schema stability, public API freeze, feature-flag gates, deployment topology, license restrictions. These become per-phase acceptance criteria.
4. **Capture verification commands.** Record exact commands the project uses — `cargo test -p foo`, `pnpm test`, `tldr diagnostics .`. Each phase will need at least one.
5. **Resolve ambiguity once, up front.** If goals or constraints are vague, ask one focused question or propose two competing plans and let the user choose. Do not bury ambiguity inside a phase.
6. **Decide durability.** Multi-turn work, anything risky, anything that will be handed off to another agent → write a durable plan file. Quick scoped work that will land this turn → return inline.

If context is still thin after step 5, **stop and report the gap** rather than producing a speculative plan.

## Planning Workflow

1. State the goal, current state, assumptions, and out-of-scope items.
2. Break the work into small, verifiable phases. Each phase should leave the build green.
3. Name the files or modules each phase is expected to touch.
4. Attach a verification step to every phase.
5. Note rollback, containment, or migration safety where it matters.
6. Surface explicit handoffs between phases (artifacts, branches, flags, schema versions).
7. Add a per-phase **Status** field initialized to `pending`.
8. Write the **Resume Protocol** so a fresh agent can pick up at any phase.

## Agent-Reusable Plan Shape

This is the **non-negotiable structure** for a plan that another agent will consume. Every plan that will be executed by a different session or subagent must include all of these sections. For the full template and worked examples, see `references/plan-template.md`.

```markdown
# Plan: <topic>

## Metadata
- Created: 2026-04-26
- Owner: <user / team / "any agent">
- Last updated: 2026-04-26
- Status: in-progress | complete | blocked
- Plan file: plans/2026-04-26-<topic>.md

## Goal
<one paragraph; what success looks like, observable from outside the code>

## Current State
<what exists today, named symbols and files, with line numbers if useful>

## Assumptions
- ...
## Unknowns
- ...
## Out Of Scope
- ...

## Invariants
<contracts that must hold across all phases — test suite green, public API stable, schema unchanged, performance budget>

## Verification Commands
<exact commands the project uses — copy-pasteable>

## Phases

### Phase 1: <imperative title>
- **Status**: pending | in-progress | complete | blocked
- **Objective**: <one sentence>
- **Files**: <concrete paths>
- **Steps**:
  1. ...
  2. ...
- **Verification**: <exact command>
- **Rollback**: <git revert / flag flip / migration down>
- **Handoff to next phase**: <artifact, branch name, flag state>
- **Notes**: <free-form, append as the phase runs>

[repeat for each phase]

## Resume Protocol
For an agent picking this up cold:
1. Read this file top to bottom.
2. Find the first phase whose status is not `complete`.
3. Read the **Notes** for any in-progress phase to recover state.
4. Run the project's verification commands to confirm the assumed state.
5. If verification disagrees with the recorded statuses, stop and surface the mismatch — do not edit silently.
```

## Why Each Section Matters For Agent Reuse

- **Metadata + Status** → the next agent can find the resume point in one glance.
- **Goal + Invariants** → the next agent has the success criteria without reading chat history.
- **Current State** → grounds the plan against the actual repo at the time of writing.
- **Verification Commands** → consistent across phases; no hunting for the right test invocation.
- **Per-phase Files** → the next agent knows what to read before editing.
- **Per-phase Rollback** → an executor that hits a snag knows how to back out.
- **Handoff** → makes inter-phase coupling explicit (what phase 2 depends on phase 1 producing).
- **Resume Protocol** → the universal entry-point instruction. Works for subagents, scheduled runs, future sessions.

## Durable Plans

Persist durable plans at:

- `plans/YYYY-MM-DD-<topic>.md`

Use a durable plan when:

- the work will span turns
- another agent (subagent, scheduled run, separate session) will execute it
- the plan needs explicit review or approval
- sequence matters and intermediate state must survive context loss

Inline plans (no file) are fine only when the plan and execution will land in the same turn with the same agent.

## When To Redirect

- only one obvious sequence of edits → skip planning, just implement
- the work needs symbolic decomposition more than sequencing → use **tasks-creating**
- the plan exists and needs running → use **plan-executing**
- risky tech choices need a freshness check → use **plan-validating** before locking the plan
- review of the plan itself is needed → use **review** or **change-plan-reviewing**

## Companion Skills

- **topic-researching** — gather current external facts before planning
- **codebase-exploring** — map the codebase area first
- **structural-code-searching** — find symbol-level usage
- **change-analyzing** — turn exploration into constraints and blast radius
- **guardrails** — check risky phases, rollback needs, and approval points
- **tasks-creating** — split a broad phase into concrete tasks
- **review** — critique the plan before execution
- **plan-validating** — check risky tech choices or migration assumptions
- **plan-executing** — run the plan once approved

## Agent Roles

Use the home agent catalog as role guidance, only when delegation is explicitly requested:

- `architectural-planning` → implementation sequencing and plan structure
- `migration-planning` → refactor and migration planning
- `durable-note-taking` → durable plan write-up when persistence is useful

## Rules

- Do not start editing code just because the plan is clear.
- Every plan that will be executed by another agent must include the Metadata, Invariants, Verification Commands, per-phase Status, and Resume Protocol.
- Prefer one ordered next action over a vague checklist.
- Keep durable plans in `plans/`, not Claude-style `thoughts/` paths.
- Each phase names a verification command; "make sure it works" is not a verification.
- Rollback notes are required for risky or irreversible phases.
- Stop and report if context is too thin for grounded planning.
- Avoid Markdown tables.

## Additional Resources

- **`references/plan-template.md`** — full agent-reusable plan template, worked examples (refactor, migration, bug-repair, feature build), and anti-patterns.
