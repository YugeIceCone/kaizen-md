# Gates — apply.gate.requires semantics + artifact validation + branching

Hand-written reference. Complements the orchestration loop in `SKILL.md` with detailed gate-enforcement, artifact-validation, and confidence-score-branching mechanics.

## Gate enforcement at advance-time (v1.30.0+)

When a workflow is schema-driven (`routine = schema:<name>` in state.json), the schema may declare `requires: [...]` per artifact. `workflow.sh advance <stage> "<summary>"` checks the current stage's required artifacts against `state.artifacts{}` BEFORE allowing the advance.

### Example schema with gates

```yaml
# domain/schemas/example.yaml (or schemas/<name>/schema.yaml)
artifacts:
  - id: plan
    template: ""
  - id: tasks
    template: ""
  - id: review
    template: ""
    apply:
      gate:
        requires: [plan, tasks]   # both must exist in state.artifacts
```

### Behavior

```bash
workflow.sh advance plan "wrote the plan"           # OK — no gate
workflow.sh advance tasks "decomposed phases"        # OK — no gate
workflow.sh advance review "needs both"              # BLOCKED:
#   [workflow] gate blocked: stage 'review' requires artifact(s) ['plan', 'tasks']
#   [workflow] record them first with `workflow.sh artifact <key> <value>`
#                                  or pass --force
# exit 4 → return 1

# Record the artifacts:
workflow.sh artifact plan plans/2026-05-12-x.md
workflow.sh artifact tasks tasks-2026-05-12.md

# Now advance succeeds:
workflow.sh advance review "tasks + plan landed"     # OK
```

### `--force` bypass

For cases where the agent legitimately needs to skip a gate (e.g., schema bug, manual override):

```bash
workflow.sh advance --force review "force bypass"
# [workflow] gate force-bypassed for stage 'review'
# [workflow] review -> next  (auto=no, subagent=no)
```

Force bypasses are logged to `state.gate_overrides[]` as audit trail:

```json
{
  "gate_overrides": [
    {"stage": "review", "at": "2026-05-12T18:20:16Z"}
  ]
}
```

## Hardcoded routines are NOT gated

Routines with `kind: hardcoded` in `routines.yaml` (audit / build-feature / fix-bug / refactor / migrate / harden / batch-migrate) accept any `advance` call without gate checks. Gate enforcement is opt-in via schema-driven routines only.

This is intentional: hardcoded routines were battle-tested in production without gates; adding them retroactively would break existing flows. Schema-driven routines are the new path forward and use gates uniformly.

## Artifact-key validation (v1.30.0+)

`workflow.sh artifact <key> <value>` validates `<key>` against the active schema's declared artifact ids:

```bash
# kaizen-default schema declares: research, explore, analyze, plan, tasks, execute, review, validate

workflow.sh artifact plan "plan.md"
# [workflow] artifact: plan=plan.md
# (OK — 'plan' is in the schema)

workflow.sh artifact analyze_findings ".workflow/a.md"
# [workflow] warning: artifact key 'analyze_findings' not in schema 'kaizen-default'
#                    (valid: ['analyze', 'execute', 'explore', 'plan', 'research', 'review', 'tasks', 'validate'])
# [workflow] artifact: analyze_findings=.workflow/a.md
# (still writes — unknown keys warn but don't reject)
```

### Strict mode

For CI gates or release flows that need to reject unknown keys:

```bash
workflow.sh artifact --strict bogus_key value
# [workflow] artifact key 'bogus_key' not in schema 'kaizen-default'
#                       (valid: ['analyze', ...])
# [workflow] strict mode: artifact write rejected
# exit 3 → return 1
```

## Confidence-Score branching (v1.17.0+)

Schemas may declare per-artifact `branch_high` / `branch_medium` / `branch_low` lists. After a stage completes with a confidence assessment, splice the remaining stages with the chosen branch:

```yaml
artifacts:
  - id: design
    template: ""
    branch_high:
      # Confident in the design — straight to implementation
      - id: implement
      - id: validate
    branch_medium:
      # Some uncertainty — add a prototype step
      - id: prototype
      - id: review
      - id: implement
      - id: validate
    branch_low:
      # Significant uncertainty — back to research
      - id: research
      - id: re-design
      - id: prototype
      - id: review
      - id: implement
      - id: validate
```

### Usage

```bash
workflow.sh advance design "design done; confidence=medium"
workflow.sh branch  design medium

# state.stages[current:] is now spliced with branch_medium's list.
# Audit trail: state.branch_decisions[] records {stage, key, new_tail, at}.
```

MCP equivalent: `workflow_branch(stage="design", key="medium")`.

### Constraints

- Requires schema-driven workflow (rejects on hardcoded routines).
- `<key>` must be one of `high`, `medium`, `low` (extensible — schemas may declare other keys).
- `<stage>` must match the current stage; otherwise the call is rejected.
- Each `branch` call appends to `state.branch_decisions[]` so the path history is preserved even after subsequent splices.

## Migrating a hardcoded routine to gated schema

If you want one of the hardcoded routines (e.g., `audit`) to use gates:

1. The schema already exists at `schemas/audit/schema.yaml` (declarative parallel).
2. Add `apply.gate.requires` to the artifacts that should gate.
3. Invoke via `workflow.sh init "audit the repo schema=audit"` — the `schema=` flag overrides verb-detection.
4. The 8-stage chain stays identical; gates layer on top.

The hardcoded `audit` (no `schema=`) still runs without gates. Both paths coexist.

## Why gates exist

Without gates, a workflow can advance past a stage whose artifact wasn't actually produced — leaving downstream stages with missing inputs and the failure mode appearing far from the cause. Gates fail-fast at the boundary: "you said you finished `analyze`, but no `analyze_report` is recorded — produce it first."

The cost is two extra lines of yaml per gated artifact. The benefit is catching missing artifacts at the stage where they should have been produced, not three stages later.

## Authoring guidance

- **Gate the artifacts that downstream stages REQUIRE**, not the ones nice-to-have.
- **Keep `requires` lists short** — 1-3 entries typical. Longer lists usually mean the stage is too big and should split.
- **Don't gate research / explore stages** — they're read-only; their output is the artifact itself.
- **Gate `execute-tasks` if you want strict plan-first discipline** — `requires: [plan, tasks]` forces both to exist before code edits begin.
- **Test gate behavior** with a synthetic workflow before deploying — see `application/_tests.py::TestGateEnforcement`.
