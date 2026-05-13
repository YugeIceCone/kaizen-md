---
name: bug-fixing
description: Diagnoses and repairs bugs or broken workflows with focused verification. Use to take a symptom from investigation through minimal code change, regression coverage, review, and validation.
metadata:
  version: "1.1"
---

# Bug Fixing

Diagnoses and repairs bugs or broken workflows with focused verification. Use this skill when the user wants a verified repair, not just a diagnosis.

## Route Choice

- use **debugging-failures** first if the root cause is unclear
- use **task** if the change is already scoped and concrete
- use **create-plan** if the repair needs multiple coordinated phases

## Fix Flow

1. Confirm the failure or concrete evidence.
2. Read the affected files, callers, and nearby tests.
3. Make the smallest credible repair.
4. Add or update regression coverage when practical.
5. Run focused verification.
6. Use **review** and **validate** when the fix is risky or broad.

## What A Good Fix Includes

- a precise repair for the observed problem
- no unnecessary scope expansion
- enough evidence to show the issue is addressed
- explicit note when the fix is partial or blocked

## Companion Skills

- **debugging-failures** -> evidence and root cause
- **task** -> single-unit implementation
- **reflect** -> critique the repair before moving on
- **review** -> findings-first critique of the change
- **validate** -> final go or no-go checks

## Agent Roles

Use the home agent catalog as role guidance:

- `bug-investigating` -> diagnosis
- `scoped-implementing` -> small contained repair
- `test-heavy-implementing` -> TDD-heavy or higher-risk repair
- `validation-reviewing` -> focused validation

Use delegation only if the user explicitly asks for it.

## Rules

- Prefer a regression test when the bug is reproducible.
- Do not claim the bug is fixed without a passing relevant check.
- If you cannot reproduce the issue, say so and state the remaining uncertainty.
- Avoid Markdown tables.
