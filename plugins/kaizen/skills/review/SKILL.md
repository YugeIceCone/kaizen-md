---
name: change-reviewing
description: Reviews code, diffs, and plans for correctness, risk, and quality. Use to inspect changes before merge or critique implementation plans.
metadata:
  version: "1.1"
---

# Change Reviewing

Reviews code, diffs, and plans for correctness, risk, and quality. Use this skill for code review, plan review, or change-risk review.

## Default Review Style

- findings first
- ordered by severity
- concrete file and line references
- brief summary only after findings

If there are no findings, say so explicitly and note any residual risk or testing gap.

## Review Modes

- Code review -> inspect changed files, tests, and nearby interfaces
- Plan review -> inspect a durable plan for sequencing, completeness, and rollback safety
- Change-risk review -> inspect impact, regression risk, compatibility, and missing validation
- Principle review -> apply one or more coding principles to surface specific violation classes

Review usually follows **plan-creating**, **task-performing**, **plan-executing**, **bug-fixing**, or **proactive-auditing**.
Use **result-synthesizing** when multiple review streams need one merged verdict.

## Coding Principle Integration

When the review scope includes code quality:

- use **coupling-reducing** to surface deep coupling and train-wreck chains
- use **logic-deduplicating** to surface duplicated business logic and shotgun-surgery risk
- use **code-simplifying** to surface complexity that reduces readability or hides bugs
- use **incremental-code-cleaning** to flag safe incremental improvements worth making alongside the change
- use **pattern-standardizing** to flag structural inconsistencies

Run **stack-detecting** first if `.agents/stack-context.md` does not exist.

## Agent Roles

Use the home agent catalog as role guidance:

- `change-plan-reviewing` -> primary review pass
- `code-reviewing` -> code quality and maintainability
- `change-plan-reviewing` -> plan completeness and change safety
- `result-synthesizing` -> synthesis for larger multi-perspective reviews
- `security-auditing` -> security-focused review when relevant

Use delegation only if the user explicitly asks for it.

## Review Process

1. Read the diff, touched files, or plan.
2. Read the tests and dependent code needed to judge impact.
3. Check behavior, edge cases, and compatibility risks.
4. Run or inspect the most relevant verification artifacts if they exist.
5. Return findings first, then open questions, then a short summary if needed.

## What To Look For

- bugs or behavioral regressions
- missing or weak tests
- plan gaps or unsafe sequencing
- missed imports, call sites, or compatibility edges
- security, performance, or migration risks when in scope
- LoD violations, DRY violations, and unnecessary complexity

## Rules

- Do not pad the answer with praise.
- Prefer direct responses over output files.
- Avoid Markdown tables.
