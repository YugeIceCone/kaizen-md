---
name: report
description: Packages results for their final destination. Use to turn validated work into user-facing answers, technical summaries, machine-readable output, or durable artifacts.
metadata:
  version: "1.1"
---

# Report Generating

Packages the result for its destination. Use this skill after the core work is complete and the remaining job is delivery.

## Reporting Modes

- direct answer -> concise user-facing result
- technical summary -> changes, verification, residual risks
- durable note -> documentation, plan update, release note, or handoff
- structured output -> JSON or other machine-oriented format when requested

## Reporting Flow

1. Identify the audience and required shape.
2. Summarize the result at the right level of detail.
3. Include the strongest evidence or verification.
4. State uncertainty and residual risk explicitly.
5. Include next steps only when they add value.

## What Good Reporting Includes

- outcome
- evidence or verification
- confidence or uncertainty
- blockers or residual risks if any
- durable file path when an artifact was created

## Companion Skills

- **result-synthesizing** -> merge multi-source results first
- **review** -> findings-first critique before final delivery
- **plan-validating** -> final confidence gate
- **memory-managing** -> decide what to persist after reporting

## Agent Roles

Use the home agent catalog as role guidance:

- `durable-note-taking` -> concise durable documentation
- `release-preparing` -> release-facing summaries when relevant

Use delegation only if the user explicitly asks for it.

## Rules

- Match the requested output shape first.
- Do not bury blockers or uncertainty under summary prose.
- Prefer short, evidence-backed delivery over exhaustive changelogs.
- Avoid Markdown tables.
