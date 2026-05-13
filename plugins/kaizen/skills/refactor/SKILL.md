---
name: code-refactoring
description: Restructures and cleans up code across one or more files. Use for extracting methods, renaming variables, or cleaning up architecture while preserving behavior.
metadata:
  version: "1.1"
---

# Code Refactoring

Restructures and cleans up code across one or more files while preserving behavior. Use this skill for multi-step refactors, extractions, restructures, and dependency cleanups.

## Core Flow
1. Analyze the target before changing code.
2. Create a small-step refactoring plan when the work is risky, multi-file, or not obviously reversible.
3. Implement one verified step at a time.
4. Review the result for regressions and design drift.
5. Validate with focused checks and the project compile barrier.

## Stage Map

- Analyze -> local exploration first; if the user explicitly asks for delegation, use `codebase-pattern-scouting` for structure and `migration-planning` for refactor analysis.
- Plan -> use `migration-planning` guidance for refactor sequencing and rollback points; persist durable plans to `plans/YYYY-MM-DD-<topic>.md` when useful.
- Implement -> use **execute-plan**; use **create-task** when a phase is still too broad; prefer `test-heavy-implementing` for TDD-heavy or high-risk work and `scoped-implementing` for small contained edits when the user explicitly asks for delegation.
- Review -> use **review**; primary review roles are `change-plan-reviewing` and `code-reviewing`.
- Validate -> use **plan-validating**; primary validation roles are `validation-reviewing`, `e2e-testing`, and `external-researching` when freshness or external best practices matter.

## Analyze

- Read the target files and the nearest tests first.
- Trace imports, call sites, and public interfaces before proposing structure changes.
- Look for behavior constraints, compatibility risks, and missing test coverage.
- Distinguish real refactoring from feature work. If the request changes behavior, call that out and plan accordingly.

## Plan

Create a durable plan when any of the following are true:

- more than one file is affected
- the order of operations matters
- rollback is non-trivial
- compatibility or migration risk is present

Plan requirements:

- break work into reversible phases
- name affected files or modules
- state verification for each phase
- state rollback or containment strategy
- separate behavior-preserving steps from any intended behavior changes

## Implement

- Execute one phase at a time.
- Keep the write scope tight.
- Add or update tests before risky internal transformations when possible.
- Run the tightest relevant checks after each phase.
- Update the durable plan if the real codebase forces a meaningful change in sequence.

## Review

Use **review** after non-trivial refactor phases or at the end of the refactor.

Review focus:

- behavior preserved
- no missed call sites or imports
- no dead compatibility shims left behind
- simpler design with no hidden coupling increase
- tests aligned with the new structure

## Validate

Use **validate** for the final gate or earlier when the refactor changes technology choices.

Validation focus:

- focused tests for the touched area
- broader compile barrier before completion
- current best-practice check if the refactor changes libraries, framework usage, or public interfaces

## Rules

- Prefer direct local execution unless the user explicitly asks for delegation.
- Do not use Claude-only `Task(...)` syntax or handoff paths.
- Do not force durable artifacts when a direct response is enough.
- Avoid Markdown tables.
