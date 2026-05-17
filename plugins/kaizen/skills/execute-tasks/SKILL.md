---
name: execute-tasks
description: Executes a batch of concrete task briefs sequentially with per-task verification. Use when the user asks to "execute tasks", "run the task list", "work through the tasks", "implement these tasks", "do the tasks in order", or when multiple scoped task briefs already exist and need disciplined one-at-a-time implementation with verification before each handoff.
metadata:
  version: "1.2"
---

# Tasks Executing

Executes multiple concrete tasks sequentially from an existing task list or set of briefs. Each task is implemented in isolation, verified locally, marked complete, and only then does the next task begin. Use this skill when several tasks already exist and need disciplined batch execution.

If tasks are not yet defined, use **tasks-creating** first. If the tasks belong to a larger phased plan with rollback notes, use **plan-executing** instead. If only one task needs running, use **task-performing**.

## When To Use

Trigger this skill when any of the following apply:

- a task list from **tasks-creating** is ready to run
- the user asks for "execute the tasks", "do them in order", "run through this list"
- a multi-task brief needs disciplined per-task verification
- a refactor or migration needs each slice landed and verified before the next

## Inputs

Confirm before starting that the following are available; gather what is missing in **Context Gathering** below:

- a task list or set of task briefs (each with objective, files, verification)
- shared invariants the batch must preserve (build green, public API stable, etc.)
- the project's verification commands (tests, lint, typecheck, build)
- the location and form for status updates (in-place edits to a plan file, a checklist comment, etc.)

## Context Gathering

Skip ahead to execution only if every item below is already settled. Otherwise gather just enough context first — a missing dependency or unclear acceptance criterion turns a clean batch into rework.

1. **Read every task brief.** Load the full task list, not just the first task. The order in the list is not always the order of execution; later tasks can reveal earlier dependencies.
2. **Map dependencies.** Note which tasks are blocked-by which. If the dependency graph is unclear or cyclic, stop and route back to **tasks-creating** rather than guess.
3. **Confirm shared invariants.** Identify the contracts that must hold across all tasks (test suite green between tasks, public API stable, schema unchanged, performance budget). These are commit-gate criteria.
4. **Capture verification commands once.** Write down the exact commands per task. If the brief is missing a verification step, add it before starting — never run a task on faith.
5. **Pick the status surface.** Decide where progress will be recorded: edits to the plan file, a `Tasks` checklist, or inline reporting back to the user. Update it after every task, not in batches.

If a task brief is too thin (no files, no verification, vague objective), **stop and route back to tasks-creating** before executing — running a context-poor task burns time on speculative implementation.

## Execution Workflow

For each task in dependency order:

1. **Focus.** Load only the current task brief; ignore later tasks.
2. **Read affected files.** Open every file in the task's Files list before editing. Note adjacent context that the brief did not mention.
3. **Implement the change.** Stay inside the declared scope. If the work spills out, stop and report rather than expanding silently.
4. **Verify locally.** Run the task's verification command(s). All must pass.
5. **Record status.** Update the agreed status surface — mark the task complete, link to the diff or commit if relevant.
6. **Stop if blocked.** A failing verification, a scope creep, or a missing dependency means stop and report — do not proceed to the next task on a yellow signal.

After every task in the batch is verified individually:

7. **Integration check.** Run a broader verification pass (full test suite, build, lint) across the whole change set to confirm tasks compose correctly.
8. **Report.** Summarize what was completed, what was skipped or blocked, and any follow-ups the user should know about.

## Per-Task Discipline

Each task gets its own verification before the next begins. Never:

- skip verification because "it's a small change"
- batch verifications across multiple tasks
- silently extend a task's scope
- continue past a failing test "just to see how far"

These shortcuts mask regressions until they are expensive to untangle.

## When To Redirect

- only one task to run -> use **task-performing**
- tasks are part of a phased plan with rollback notes -> use **plan-executing**
- task briefs are vague or missing files / verification -> use **tasks-creating** to firm them up first
- a task fails verification and the cause is unclear -> use **debugging-failures**
- the overall direction is unclear -> use **workflow-routing**

## Companion Skills

- **tasks-creating** — produce or refine the task briefs
- **task-performing** — execute one task brief in detail
- **plan-executing** — run a phased plan with rollback discipline
- **debugging-failures** — isolate a failing verification before continuing
- **review** — sanity-check the full batch diff before reporting done
- **verification-before-completion** — confirm every claim of "done" is backed by a passing command

## Rules

- Execute tasks one at a time, in dependency order.
- Verify every task before starting the next.
- Stop and report immediately if a task is blocked, scope-creeps, or fails verification.
- Maintain the shared status surface durably; do not leave silent gaps.
- Never expand a task's scope without surfacing the change.
- Run an integration check after the batch, not just per-task checks.
- Avoid Markdown tables.

## Additional Resources

- **`references/execution-patterns.md`** — patterns for status tracking, partial-batch handoff, blocker reporting, and recovering from a failing task mid-batch
