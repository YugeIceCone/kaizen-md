---
name: workflow-supervising
description: Coordinates multi-stage workflows from start to finish. Use when choosing the next stage, tracking progress, and deciding when to replan or pause.
metadata:
  version: "1.1"
---

# Workflow Supervising

Coordinates multi-stage workflows from start to finish. Owns the run state and decides which stage runs next, when to pause, and when to declare the workflow complete.
It should decide which stage runs next, when to pause, and when to declare the workflow complete.

## When To Use It

- the request spans research, planning, implementation, review, and delivery
- the next correct stage is not obvious from the initial prompt
- the work needs replanning, checkpoints, or continuity across turns
- the user wants end-to-end handling instead of a single stage

## Core Loop

1. Restate the goal, current state, and constraints.
2. Choose the smallest correct next stage.
3. Check **guardrails** before risky or irreversible work.
4. Run or route to the chosen stage.
5. Ask **reflect** to critique significant intermediate results.
6. Replan, continue, or finish based on the result.
7. Route through **review**, **validate**, and **report** before final delivery when appropriate.

## Good Supervisor State

Track:

- goal
- active stage
- completed stages
- blockers and open questions
- durable plan path if one exists
- next required checkpoint

## Companion Skills

- **workflow-routing** -> choose the most specific next stage
- **guardrails** -> safety, scope, and checkpoint checks
- **create-plan** -> phased work breakdown
- **execute-plan** -> carry out approved phased plans
- **execute-tasks** -> execute multiple concrete tasks sequentially
- **execute-task** -> execute a single task from a brief
- **result-reflecting** -> self-critique and replan decisions
- **result-synthesizing** -> merge parallel or multi-perspective results
- **report-generating** -> final delivery shape

## Delegation Reference

If the user explicitly asks for delegation or sub-agents:

- use the role guidance in the agent catalog
- keep ownership and write scope explicit
- prefer local work when the next step is on the critical path


## Agent Roles

Use the home agent catalog as role guidance:

- `multi-agent-coordinating` -> multi-step coordination
- `architectural-planning` -> sequencing and plan structure
- `durable-note-taking` -> durable run notes when a file artifact is useful

Use delegation only if the user explicitly asks for it.

## Rules

- Prefer the minimal next stage over a giant monolithic workflow.
- Keep one verified stage in progress at a time.
- Default to local orchestration unless explicit delegation is requested.
- Prefer direct responses over mandatory handoff files.
- Avoid Markdown tables.
