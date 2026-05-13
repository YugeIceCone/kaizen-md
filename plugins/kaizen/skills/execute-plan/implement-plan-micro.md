---
name: implement-plan-micro
description: Execute a short approved plan locally in tightly verified steps. Use when the work is smaller than a full execute-plan run but still benefits from explicit sequencing and per-step verification.
---

# Implement Plan Micro

Use this when a plan already exists and the next work slice is small, local, and tightly coupled.

If the plan is broad or spans several substantial phases, use `$execute-plan` instead.

## Inputs

- a durable plan file or explicit ordered micro-step list
- the next step to execute
- the verification command or check for that step

## Flow

1. Read the plan and the targeted step completely.
2. Read the named files, usages, and nearby tests.
3. Execute one concrete step locally.
4. Run the tightest relevant verification immediately.
5. Record progress in the existing plan if the work is durable.
6. Stop and report if verification fails or the codebase mismatches the plan.

## Companion Skills

- `$execute-plan` -> larger phased execution
- `$task` -> one concrete change with verification
- `$reflect` -> self-check after a non-trivial micro-step
- `$report` -> package the result

## Rules

- prefer local execution over delegation
- keep the micro-step and verification paired
- do not depend on `thoughts/`, handoff directories, or `Task(...)`
- avoid Markdown tables
