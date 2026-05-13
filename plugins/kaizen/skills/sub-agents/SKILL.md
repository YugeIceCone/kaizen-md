---
name: sub-agent-managing
description: Provides internal sub-agent reference and delegation guidance. Use when explicit delegation is requested to manage agent roles, models, and scope.
metadata:
  version: "1.1"
---

# Sub-Agent Managing

Internal sub-agent reference and delegation guidance. Use this only when the user explicitly asks for delegation, sub-agents, or parallel agent work.

## Default Position

- keep work local unless explicit delegation is requested
- use `agents/` as the home-level agent catalog
- treat agent files as guidance, not a built-in runtime registry

## Practical Guidance

- choose the smallest agent role that matches the task
- keep delegated work scoped to a concrete objective
- give each delegated task an explicit write scope when code changes are involved
- keep the main thread focused on integration and critical-path work

## Model Guidance

- Choose the most capable available model for heavyweight planning, implementation, and review.
- Use lighter models for bounded exploration and support work.
- Omit `model` to inherit from the current session.

## Compatibility Dry-Runs

For deterministic local dry-runs of older agent-tool examples, use:

- `python3 scripts/legacy_tool_shims/task_tool.py --subagent-type reviewer --prompt "Review the diff"`
- `python3 scripts/legacy_tool_shims/ask_user_question.py --question "Which path?" --option "A::Recommended" --option "B::Alternative"`

## File Locations
- home-level agents -> `agents/`
- repo-local agents -> repo-local guidance only when the project defines it

## Companion Skills

- **workflow-supervising** -> orchestration and delegation decision
- **workflow-routing** -> pick the correct stage first

## Rules

- explicit delegation only
- do not use Claude-only model names or CLI examples
- avoid Markdown tables
