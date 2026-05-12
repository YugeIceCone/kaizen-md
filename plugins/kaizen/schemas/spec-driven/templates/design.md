# Design — <feature-name>

> Authored: <YYYY-MM-DD>
> Owner: <handle>
> Status: draft | review | accepted
> Source requirements: `requirements.md`

## Adaptive strategy (from Confidence Score in requirements.md)

- **High (>85%)** — comprehensive plan + automated implementation. Skip PoC.
- **Medium (66–85%)** — build PoC / MVP first with clear success criteria; expand incrementally.
- **Low (<66%)** — research phase first; analyze comparable implementations; re-run ANALYZE before proceeding.

Chosen strategy: <high|medium|low> — <rationale>.

After completing this document, inspect the schema's branch paths to know which downstream stages apply:

```bash
/kaizen:schema branches spec-driven design
# → {high: [...], medium: [...], low: [...]}
```

Then advance the workflow with the rationale recorded:

```bash
workflow.sh advance design "confidence=<level>; choosing <path>: <why>"
```

The workflow.sh state machine itself walks every stage in topo order. The branch lists are **advisory** — they tell the agent which stages are most relevant for the chosen confidence tier. Stages not in the chosen branch can be tick-noted as "skipped: outside <level>-confidence path" rather than re-doing them.

## Architecture overview

<one-paragraph high-level: components, boundaries, integration surface>

## Component diagram

```
<ascii or mermaid component layout>
```

## Sequence diagrams

```
<ascii or mermaid sequence — one per critical flow>
```

## Data model

| Entity | Fields | Constraints | Storage |
|--------|--------|-------------|---------|
| <name> | <field: type> | <invariant> | <table / file / cache> |

## Interfaces / API contracts

- **<endpoint or function signature>**
  - Input: <type / schema>
  - Output: <type / schema>
  - Pre-condition: <REQ-### ref>
  - Post-condition: <REQ-### ref>

## Error matrix

| Error condition (IF ...) | Detection | Response (THEN ...) | REQ ref |
|--------------------------|-----------|---------------------|---------|
| <condition>              | <how>     | <recovery>          | REQ-### |

## Unit testing strategy

- <module>: <coverage target %> via <framework>; mock <dependencies>.
- Edge cases enumerated in requirements.md tested in <test file>.

## Cross-references

- Decision records for non-trivial choices → `decisions.md`
- Per-task breakdown → `tasks.md`
