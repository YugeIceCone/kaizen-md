---
name: validate
description: Validates plans or risky changes against current best practices and local project checks. Use for a go or no-go recommendation before or after implementation, especially when freshness matters.
metadata:
  version: "1.1"
---

# Plan Validating

Validates a plan or risky change against current best practices and local project checks. Use this skill for pre-implementation plan validation and post-implementation final validation.

## Validation Targets

- new library or framework choices
- migration or refactor plans with compatibility risk
- risky integrations or architecture changes
- completed work that needs a final go or no-go pass
- **Current best practices via Context7.** Where the validation hinges
  on "is this still the right way?", check the library's current docs
  through Context7 — its docs track upstream versions, so it catches
  practices that were correct when written but have since changed.

## External Validation

When freshness matters:

- check official docs first
- check current deprecations or best practices
- cite sources and dates
- state uncertainty explicitly if web access or evidence is incomplete

Use `external-researching` role guidance when external research is needed.

## Local Validation

- run focused tests for the touched area
- run broader project checks before final completion
- verify any acceptance criteria named in the plan

Use `validation-reviewing` for focused test validation and `e2e-testing` for broader workflow validation when the user explicitly asks for delegation.

## Assessment Labels

- `validated` -> safe to proceed
- `needs-review` -> concerns exist but may be acceptable with discussion
- `must-change` -> deprecation, security risk, or major plan flaw blocks progress

## Output Shape

- target being validated
- findings by choice, area, or verification check
- recommendation per issue
- overall status
- sources used when external research was needed

## Persistence

- Return findings directly by default.
- Write a durable note only if the user asks or if the surrounding workflow needs one.
- If a durable artifact is needed, prefer the current workspace or `plans/`.

## Rules

- Do not guess on current best practices when they can be checked.
- Separate evidence from recommendation.
- Do not depend on Claude handoffs or `thoughts/` paths.
- Avoid Markdown tables.
