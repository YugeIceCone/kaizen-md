---
name: synthesize
description: Merges multiple outputs into one coherent result. Use when parallel findings, overlapping reviews, competing plans, or research from several sources must be reconciled.
metadata:
  version: "1.1"
---

# Result Synthesizing

Merges multiple inputs that need one coherent output. Use this skill when parallel findings, overlapping reviews, or research from several sources must be reconciled into a single answer.

## When To Use It

- parallel exploration or research produced overlapping findings
- several review passes need one verdict
- multiple plan variants need one recommended path
- the final answer must combine code, tests, risks, and next steps

## Synthesis Flow

1. Normalize the inputs to the same question or target.
2. Identify what they agree on.
3. Identify contradictions, uncertainty, and missing evidence.
4. Keep the strongest supported claims.
5. Preserve unresolved disagreements explicitly.
6. Produce one merged result plus any required follow-up.

## Output Shape

- common ground
- conflicts or open questions
- merged recommendation or answer
- evidence worth carrying forward
- next stage if more work is required

## Companion Skills

- **topic-researching** -> gather more evidence if conflicts are unresolved
- **review** -> critique the merged result
- **plan-validating** -> verify the merged recommendation
- **report-generating** -> format the synthesized result for delivery

## Agent Roles

Use the home agent catalog as role guidance:

- `code-reviewing` -> multi-perspective synthesis
- `durable-note-taking` -> concise final write-up
- `architectural-planning` -> merge design or planning perspectives

Use delegation only if the user explicitly asks for it.

## Rules

- Do not hide meaningful disagreement.
- Do not average away a serious risk just because other inputs are positive.
- Prefer evidence-backed convergence over rhetorical neatness.
- Avoid Markdown tables.
