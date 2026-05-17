---
name: task
description: Executes single concrete implementation tasks from formal briefs, plan steps, or scoped requests. Use when changes need edits, focused verification, and clear outcomes.
metadata:
  version: "1.2"
---

# Task Performing

Executes a single concrete implementation task — whether from a formal task brief, a plan step, or a tightly scoped user request. Use this skill when the next unit of work is already small, concrete, and ready to implement.

If the work still needs sequencing, use **plan-creating** or **task-creating** first.

## Inputs

- a single task brief, plan step, or tightly scoped user request
- affected files and nearby tests
- acceptance criteria or verification command if known
- invariants to preserve (from a formal brief if one exists)

## Execution Loop

1. Read the task and confirm the intended scope.
2. Read the affected files, callers, imports, configs, and nearby tests.
3. Implement the smallest change that satisfies the task.
4. Add or update regression coverage when the task changes behavior or fixes a bug.
5. Run focused verification for the touched area.
6. Return the result, evidence, and any blocker.

## When To Redirect

- use **debugging-failures** if the root cause is still unclear
- use **bug-fixing** if the work starts from a symptom rather than a scoped task
- use **task-creating** if the task expands into multiple independent units
- use **plan-executing** if the task is only one step inside a larger approved plan

## TDD And Testing

- When the user requests TDD, or when a bug fix clearly needs regression protection, write the failing test first.
- Use **tdd-implementing** when the task should be run under a stricter red-green-refactor workflow.
- Do not claim success without the relevant check passing.

## Agent Roles

Use the home agent catalog as role guidance:

- `scoped-implementing` -&gt; small focused implementation
- `test-heavy-implementing` -&gt; TDD-heavy or higher-risk task execution

Use delegation only if the user explicitly asks for it.

## Persistence

- Return results directly by default.
- Update the existing durable plan when the task belongs to one.
- Write a separate note only if the user asks or if a durable artifact is genuinely useful.

## After Execution

- Use **result-reflecting** if the task result should be critiqued before the workflow continues.
- Use **review** for external critique on non-trivial changes.
- Use **report-generating** when the remaining job is delivery.

## Rules

- Keep the write scope tight.
- Do not create mandatory Claude-style handoffs.
- Report blockers clearly when scope, evidence, or verification is insufficient.
- Avoid Markdown tables.
