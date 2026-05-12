---
name: result-reflecting
description: Critiques intermediate results before they move forward. Use after research, implementation, or planning to compare output against the goal, score confidence, and decide whether to proceed.
metadata:
  version: "1.1"
---

# Result Reflecting

Critiques the current result before it moves forward. Use this skill when an intermediate result needs a disciplined self-check before the workflow continues.

## Reflection Questions

- did this answer the actual goal
- what evidence supports the answer
- what is still missing or unverified
- what could break if this is wrong
- should the workflow continue, replan, or escalate

## Reflection Loop

1. Restate the target result and the original goal.
2. Compare the current output to the success criteria.
3. Separate supported claims from guesses.
4. Identify missing coverage, contradictions, or unsafe assumptions.
5. Emit a status and the smallest corrective next step.

## Status Labels

- `pass` -> ready for **review**, **plan-validating**, or **report-generating**
- `needs-replan` -> route back to **create-plan**, **create-task**, or **change-analyzing**
- `needs-review` -> result is plausible but should be checked externally

## Output Shape

- target reviewed
- strengths backed by evidence
- gaps or risks
- confidence -> low, medium, or high
- next stage

## Companion Skills

- **change-analyzing** -> when the real problem is still unclear
- **create-plan** -> when the critique shows the sequence is wrong
- **review** -> for external critique after self-reflection
- **plan-validating** -> for final go or no-go checks
- **report-generating** -> when the result is ready to deliver

## Agent Roles

Use the home agent catalog as role guidance:

- `code-reviewing` -> stricter structured critique
- `change-plan-reviewing` -> findings-first risk scan

Use delegation only if the user explicitly asks for it.

## Rules

- Critique against the goal, not against stylistic preferences.
- Be explicit about what is evidence versus inference.
- If confidence is low, do not let the workflow silently continue.
- Avoid Markdown tables.
