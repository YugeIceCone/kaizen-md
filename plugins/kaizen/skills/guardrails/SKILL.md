---
name: risk-guarding
description: Applies policy and risk checks before the workflow proceeds. Use before destructive actions, external communication, or risky tool calls to ensure safety and compliance.
metadata:
  version: "1.1"
---

# Risk Guarding

Applies policy and risk checks before the workflow proceeds. Use this skill when the workflow is about to do something risky, irreversible, expensive, or policy-sensitive.

**guardrails** is a gate, not a replacement for planning or review.

## Guardrail Checks

- is the requested action in scope
- is it destructive or hard to reverse
- does it depend on fresh external facts
- could it expose secrets, unsafe output, or policy violations
- does it need a human checkpoint before continuing
- does infrastructure work have a real execution path and verification plan

## Status Labels

- `clear` -> safe to continue
- `needs-checkpoint` -> pause for user or policy approval
- `blocked` -> do not continue until the issue is resolved

## Guardrail Flow

1. Restate the pending action.
2. Identify the irreversible or risky parts.
3. Check scope, safety, freshness, and verification expectations.
4. Decide whether to continue, pause, or block.
5. State the minimum action needed to unblock safely.

## When To Use It

- before destructive shell or git operations
- before release or production delivery
- before large migrations or security-sensitive changes
- before final output when legal, safety, or compliance risk matters
- when infrastructure changes may be unwired or unverified

## Companion Skills

- **workflow-supervising** -> route the workflow through the gate
- **plan-validating** -> evidence-backed final decision
- **change-reviewing** -> findings-first critique of risky changes
- **report-generating** -> communicate the gate outcome clearly

## Source Patterns To Preserve

- observe actual outputs before editing
- verify infrastructure is wired end to end
- do not mark work complete until the real execution path is proven
- require a checkpoint before irreversible actions

## Agent Roles

Use the home agent catalog as role guidance:

- `security-auditing` -> security and safety review
- `validity-checking` -> focused verification checks
- `regression-checking` -> broader workflow validation
- `change-plan-reviewing` -> risk-focused review

Use delegation only if the user explicitly asks for it.

## Rules

- Do not use a vague risk warning when you can name the exact blocker.
- Do not let the workflow proceed on unverified assumptions when the cost of being wrong is high.
- Be specific about the checkpoint or evidence required to continue.
- Avoid Markdown tables.
