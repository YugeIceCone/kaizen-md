---
name: create-tasks
description: Breaks plan phases or broad requests into concrete, verifiable execution tasks. Use when the user asks to "create tasks", "break this into tasks", "decompose this phase", "split this into work units", "make a task list", "what tasks are needed for X", or when a plan phase or feature request is too large to implement directly and needs scoped briefs with files, constraints, and verification.
metadata:
  version: "1.2"
---

# Tasks Creating

Decomposes a plan phase, feature request, or bug repair into one or more concrete execution tasks. Each task is small enough to implement directly, names its files or modules, and carries its own verification check.

If only one obvious small step is needed, skip this skill and use **task-performing** instead. If the work spans multiple phases that need ordering and rollback notes, use **plan-creating** first.

## When To Use

Trigger this skill when any of the following apply:

- a plan phase spans too many files to implement in one pass
- ownership or order inside the next phase is unclear
- a bug fix needs separate reproduction, repair, and cleanup tasks
- the user asks for a "checklist", "task list", or "next steps"
- batch work needs sequential tasks for **tasks-executing** to consume

## Inputs

Confirm the following are available; gather what is missing in **Context Gathering** below:

- the plan, request, or phase to decompose
- known constraints, invariants, or acceptance criteria
- target files, modules, or interfaces (if known)
- the verification commands the project uses (tests, lint, typecheck, build)

## Context Gathering

Skip ahead to decomposition only if every item below is already settled. Otherwise gather just enough context first — context-poor tasks waste downstream cycles.

1. **Read the source.** Open the plan file or scroll back to the request. Note which phase or section is in scope and what is explicitly out of scope.
2. **Map the surface area.** Identify the files, symbols, and external interfaces the work touches. Use **codebase-exploring** for unfamiliar regions and **structural-code-searching** for symbol-level mapping.
3. **Confirm invariants.** Note the contracts that must hold across tasks (test suite green, public API stable, schema unchanged, performance budget). These become per-task acceptance criteria.
4. **Resolve ambiguity once.** If the request is vague ("clean this up", "make it better"), ask the user one focused question or propose two concrete decompositions and let them choose. Do not invent intent.
5. **Capture verification commands.** Record the exact commands each task will run — `cargo test -p foo`, `pnpm test path/to/file`, `tldr diagnostics .`, etc. Each task needs a verification step it can prove on its own.

If context is still missing after step 4, **stop and report the gap** rather than producing speculative tasks.

## Decomposition Workflow

1. Read the in-scope phase or request in full.
2. Identify the smallest useful execution units that can be verified independently.
3. Separate read-only discovery from code changes when discovery would otherwise be repeated.
4. Attach concrete files, interfaces, or commands to each task.
5. Add verification and completion criteria for each task.
6. Order the tasks so later work depends on already-verified earlier work.
7. Surface explicit handoffs between tasks (artifacts, branches, flags).

## Good Task Shape

Each task brief answers, at minimum:

- **Objective** — one sentence, action-verb led
- **Scope** — what is in, what is out
- **Files / modules** — concrete paths or symbols
- **Invariants** — what must still hold after the change
- **Verification** — exact command or check that proves the task is done
- **Blocked-by / blocks** — sequencing relationship to other tasks
- **Redirect signals** — symptoms that mean the task should pause and re-route

For full task templates (refactor split, bug repair, migration slice, spike-then-execute, characterization tests), see `references/task-templates.md`.

## Output Forms

Pick the output form that matches downstream use:

- **Inline brief list** — when the user wants the tasks in chat and will execute immediately.
- **Appended to plan file** — when the tasks belong to an approved plan; write under a `## Tasks` section beside the relevant phase.
- **Standalone task file** — when **tasks-executing** or another agent will consume them later. Use a clear name (e.g. `plans/auth-refactor-tasks.md`).

Persist tasks beside the plan they belong to. Do not put durable task lists in handoff-only directories.

## When To Redirect

- only one small change is needed -> use **task-performing**
- the work needs phasing, rollback, or risk notes first -> use **plan-creating**
- the failing symptom is not yet isolated -> use **debugging-failures** before creating repair tasks
- task boundaries or sequencing feel risky -> use **review** before handing off

## Companion Skills

- **plan-creating** — build the higher-level phased sequence first
- **task-performing** — execute a single task brief
- **tasks-executing** — execute a batch of task briefs sequentially
- **plan-executing** — run an approved phased plan
- **debugging-failures** — isolate a failing symptom before producing repair tasks
- **review** — critique risky task boundaries or sequencing
- **codebase-exploring** / **structural-code-searching** — gather surface-area context

## Agent Roles

Use the home agent catalog as role guidance, only when the user explicitly delegates:

- `architectural-planning` — task decomposition and ordering
- `migration-planning` — refactor and migration task slicing
- `durable-note-taking` — durable task write-up when persistence is requested

## Rules

- Do not invent extra tasks to lengthen the list — every task must earn its place with verifiable output.
- Prefer tasks that can be verified independently; serialize only when a real dependency exists.
- Each task names the verification command it will run.
- Keep durable task notes beside the plan, not in handoff-only directories.
- Stop and report if context is too thin for grounded decomposition.
- Avoid Markdown tables.

## Additional Resources

- **`references/task-templates.md`** — task brief skeletons and worked examples (refactor, bug repair, migration, spike, characterization tests)
