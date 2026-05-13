---
name: change-analyzing
description: Assesses blast radius, affected interfaces, and risks for a proposed change or bug fix. Use when the question is "what matters for this change and what can break?" — after exploration or research, before planning or editing.
metadata:
  version: "1.1"
---

# Change Analyzing

Assesses blast radius, affected interfaces, and risks for a proposed change or bug fix. Use this skill after the relevant area is understood and before committing to the next action.

## Analysis Questions

- what files, modules, or interfaces are actually affected
- what callers, configs, schemas, or tests depend on them
- what invariants must remain true
- what can break if the change is wrong
- whether the work is a single task, a bug investigation, or a phased plan

## Analysis Flow

1. Restate the proposed change, question, or failure mode.
2. Read the directly affected code and the nearest dependents.
3. Trace public interfaces, callers, and tests.
4. Identify risks, unknowns, and missing evidence.
5. Decide the next stage: **create-plan**, **task**, **debug**, **review**, or **validate**.

## What To Capture

- current behavior
- affected surface area
- compatibility and migration risks
- test coverage and missing checks
- rollback or containment concerns
- assumptions that still need confirmation

## Good Output Shape

- current state
- affected files and interfaces
- main risks or unknowns
- recommended next stage

## Companion Skills

- **explore** -> gather structure before analysis
- **research** -> fill external knowledge gaps
- **create-plan** -> when the work needs ordered phases
- **task** -> when the work is already small and concrete
- **debug** -> when the root cause is still unclear

## Agent Roles

Use the home agent catalog as role guidance:

- `migration-planning` -> refactor and migration analysis
- `codebase-exploring` -> structure and dependency analysis
- `bug-investigating` -> failure analysis and debugging context

Use delegation only if the user explicitly asks for it.

## Rules

- Do not pretend uncertainty is settled.
- Prefer concrete file references over abstract advice.
- Avoid Markdown tables.
