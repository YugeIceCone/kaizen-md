---
name: memory-state
description: Manages short-term workflow state and long-term memory. Use when deciding what to recall before acting, what to persist after learning, and how to preserve continuity.
metadata:
  version: "1.1"
---

# Memory Managing

Manages short-term workflow state and long-term memory deliberately. Use this skill when continuity matters and the workflow should not rely on ad hoc memory.

## State Scopes

- short-term state -> goal, current stage, blockers, active files, recent decisions
- durable workflow state -> plan files, progress notes, and user-approved artifacts
- long-term memory -> reusable learnings, patterns, failures, and architectural decisions

## Memory Flow

1. Decide whether prior learnings are likely to help.
2. Recall only the smallest useful set of past context.
3. Keep active workflow state in the current plan or progress record.
4. Persist only high-signal decisions, fixes, or failures.
5. Before ending a long workflow, leave enough durable state for the next turn to resume cleanly.

## When To Recall

- before planning a repeated kind of change
- before debugging a familiar failure mode
- when the user asks what happened before or what worked previously
- when architecture or convention history matters

## When To Persist

- a validated fix or proven failure mode
- a durable architectural decision
- a reusable workflow pattern
- the minimal context needed to resume later

## Local Tooling

When current tooling is available, prefer the smallest relevant query:

- `scli recall "query"`
- `scli learnings --k 20`
- `scli stats`

Use project memory tools only when they materially help the current task.

## Companion Skills

- **workflow-supervising** -> track run state across stages
- **create-plan** -> keep durable workflow state in one place
- **result-reflecting** -> decide whether a learning is worth persisting
- **report-generating** -> summarize what should be carried forward

## Agent Roles

Use the home agent catalog as role guidance:

- `durable-note-taking` -> durable state or continuity notes

Use delegation only if the user explicitly asks for it.

## Rules

- Do not create handoff files by default.
- Recall before reading large histories from scratch.
- Persist only high-signal context that will help a future task.
- Prefer plan updates over scattering state across many files.
- Avoid Markdown tables.
