---
name: execute-plan
description: Executes an agent-reusable plan in phased, verifiable steps with durable status updates. Use when the user asks to "execute the plan", "run the plan", "implement the plan", "continue the plan", "resume from plan X", "pick up the plan from phase Y", or when a plan file (or explicit ordered step list) already exists and should be advanced one phase at a time. Designed so subagents and fresh sessions can resume from any phase using the plan's Resume Protocol.
metadata:
  version: "1.2"
---

# Plan Executing

Executes an agent-reusable plan one phase at a time, with verification before each handoff and durable status updates so any agent can resume the work later. Use this skill when the plan already exists and the main task is execution, not planning.

If no plan exists, use **plan-creating** first. If only a single isolated step needs running, use **task-performing**. If a batch of unphased tasks needs running, use **tasks-executing**.

## When To Use

Trigger this skill when any of the following apply:

- a plan file exists in `plans/` with a Phases section
- the user references a specific plan by name or path
- the user asks to "resume", "continue", or "pick up where we left off" with a known plan
- a subagent or scheduled job hands a plan path to execute

## Inputs

Confirm before starting; gather what is missing in **Context Gathering** below:

- the plan file path, or an explicit ordered step list from the user
- the project's verification commands (the plan should already list them)
- the location for status updates (the plan file itself)

If neither a plan file nor an ordered step list exists and sequencing matters, **stop and route to plan-creating** rather than improvising a plan in the executor.

## Context Gathering

Before touching code, follow the plan's **Resume Protocol** — the plan is the authoritative source of context.

1. **Read the plan top to bottom.** Goal, Current State, Assumptions, Unknowns, Out Of Scope, Invariants, Verification Commands, all Phases. Do not skip ahead to "the next phase" — earlier sections set the rules for execution.
2. **Find the resume point.** First phase whose Status is not `complete`.
3. **Recover partial state.** Read the in-progress phase's **Notes** field. It records what the previous executor (you, a subagent, or a prior session) tried, what passed, what failed.
4. **Confirm the assumed state matches reality.** Run the previous (complete) phase's Verification command. If it now fails, the recorded state has drifted — stop and surface the mismatch, do not silently continue.
5. **Re-read affected files for the resume phase.** Do not edit on memory — open the files listed in the phase before changing anything.
6. **Confirm invariants still hold.** Run a quick subset of project verification (typecheck, smoke test) to make sure earlier phases left the world consistent.

If the plan is missing required sections (Verification Commands, per-phase Status, Resume Protocol), stop and route back to **plan-creating** to firm it up. A context-poor plan is worse than no plan.

## Execution Loop

For each phase, in order:

1. **Set Status to `in-progress`** in the plan file. Update `Last updated`.
2. **Read affected files** named in the phase's Files list.
3. **Implement the phase's Steps** in order. Stay inside the declared scope.
4. **Run the phase's Verification command.** All must pass.
5. **Update Notes** with: command output summary, commit hash if the project uses git, any caveats discovered.
6. **Set Status to `complete`** in the plan file.
7. **Move to the next phase** only after step 6 is recorded.

Stop and report immediately if:

- verification fails — set Status to `blocked`, record cause in Notes, do not silently retry
- the phase needs files outside its declared scope — re-route to **plan-creating** to expand the phase
- an invariant is violated by an earlier phase that was marked complete — re-open the earlier phase
- the plan's assumptions no longer match reality — surface the mismatch before continuing

## Status Discipline

The plan file is the durable status surface. Update it:

- **Before** starting a phase (`pending` → `in-progress`)
- **As** the phase runs (append to Notes after each significant step)
- **After** verification passes (`in-progress` → `complete`)
- **On block** (`in-progress` → `blocked`, with cause in Notes)

Never:

- batch status updates at session end
- mark a phase complete before its Verification command passes
- silently extend a phase's scope
- skip the Notes update — the next agent depends on it

For full status patterns, sub-agent dispatch examples, and recovery flows, see `references/execution-protocol.md`.

## Sub-Agent Dispatch

Because the plan is self-contained, a phase can be handed to a subagent with a one-paragraph prompt:

```
Read plans/2026-04-26-auth-iface.md.
Execute Phase 2 only. Do not touch other phases.
Follow the plan's Resume Protocol and Execution Loop.
Update Status and Notes in the plan file.
Return when verification passes or stop and report on block.
```

Use **dispatching-parallel-agents** when phases are independent (no Blocked-by relationship). Otherwise execute serially.

## Mismatches With Reality

If the codebase no longer matches the plan's Current State or Assumptions:

1. **State the mismatch clearly** in the plan's Notes for the affected phase.
2. **Decide whether intent still holds.** Sometimes the goal is still valid even though the path changed.
3. **Adjust the plan**, not the code, if intent holds. Bump `Last updated`. Surface the change to the user before continuing.
4. **Stop the execution** and route to **plan-creating** if intent no longer holds.

Never silently rewrite the plan to match what was already done — that destroys the audit trail.

## Verification

- Run the **per-phase Verification command** after each phase. The plan provides it; do not invent your own.
- Run the project's **compile barrier** (`pnpm tsc --noEmit`, `cargo check`, `tldr diagnostics .`) before declaring the plan complete.
- After all phases are complete, run a **broader verification pass** — full test suite, build, smoke test — to confirm the phases compose correctly.
- If the phase has no Verification command, stop. The plan is broken.

## When To Redirect

- plan does not exist or is too thin → use **plan-creating**
- only one isolated change is needed → use **task-performing**
- a batch of unphased tasks → use **tasks-executing**
- a phase fails verification with unclear cause → use **debugging-failures**
- the plan needs decomposition mid-phase → use **tasks-creating** to expand the phase in place
- approach itself looks wrong → use **review** or **change-plan-reviewing** before continuing

## Companion Skills

- **plan-creating** — write or extend the plan
- **tasks-creating** — split a phase into tasks
- **task-performing** — execute one task brief
- **tasks-executing** — run a batch of unphased tasks
- **debugging-failures** — isolate a failing verification
- **review** — inspect non-trivial implementation phases
- **report-generating** — package results once the plan is complete
- **plan-validating** — final go or no-go check on risky work
- **verification-before-completion** — confirm "done" claims with passing commands
- **dispatching-parallel-agents** — run independent phases in parallel via subagents

## Agent Roles

Use the home agent catalog as role guidance, only when delegation is explicitly requested:

- `test-heavy-implementing` — multi-file or TDD-heavy phase
- `scoped-implementing` — small focused phase from a larger plan
- `migration-completing` — late-stage migration phases
- `durable-note-taking` — durable progress note when the user wants a separate file artifact

## Rules

- Follow the plan's Resume Protocol on every entry — you are not the only agent that may execute this plan.
- Update the plan file's Status and Notes as you go, not at session end.
- Run the phase's Verification command before marking complete.
- Stop and report on any failure or scope creep — never silently widen scope or skip verification.
- Keep the plan and implementation synchronized; surface drift, do not paper over it.
- Run integration verification after the final phase, not just per-phase checks.
- Avoid Markdown tables.

## Additional Resources

- **`references/execution-protocol.md`** — full status patterns, sub-agent dispatch examples, mid-plan failure recovery, mismatch handling, and integration verification.
