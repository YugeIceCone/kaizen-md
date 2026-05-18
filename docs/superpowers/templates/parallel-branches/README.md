# Parallel-branches kit (schema-driven)

Reproducible architecture for **MASTER PLAN → PARALLEL BRANCHES → MERGE** workflows. All artifacts are schema-validated so the same plan rendered in YAML produces deterministic dispatch + verification regardless of who runs it.

## Files

```
parallel-branches/
├── README.md                                ← this file
├── schemas/
│   ├── master-plan.schema.json              ← validates a master-plan YAML
│   ├── chunk-ledger.schema.json             ← per-chunk progress ledger JSONL row
│   ├── perms-fragment.schema.json           ← .chunks/N/perms.json
│   ├── progress-fragment.schema.json        ← .chunks/N/progress.md
│   ├── backlog-fragment.schema.json         ← .chunks/N/backlog.jsonl row
│   └── merge-action.schema.json             ← validates the merge step's action list
├── rubrics/
│   └── chunk-sizing.yaml                    ← decision-rubric: signals → recommended decomposition
└── examples/
    ├── master-plan.example.yaml             ← worked example (coverage-axes)
    └── chunk-ledger.example.jsonl           ← per-chunk progress trace
```

## Mental model

```
┌────────────────────────────────────────────────────────────────┐
│  PHASE 0  master-plan.yaml  (validated by master-plan.schema)  │
└──────────────────────────┬─────────────────────────────────────┘
                           │ rubric (chunk-sizing.yaml)
                           │   walks signals (total_items,
                           │   per_axis_cost_k, slots_available,
                           │   token_budget_constrained)
                           ▼
                  ┌──────────────────┐
                  │ recommended N    │
                  │ + per-chunk      │
                  │ budget_tokens    │
                  └────────┬─────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  PHASE 1  N parallel agents, each owning disjoint files +      │
│           a .chunks/<id>/ fragment dir                          │
│           (perms.json / progress.md / backlog.jsonl /          │
│            mcp-mounts.txt — all schema-validated)              │
└──────────────────────────┬─────────────────────────────────────┘
                           │ all branches merge to master
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  PHASE 2  MERGE  (actions list — schema-validated)             │
│           consolidate_perms → append_progress → ...            │
└────────────────────────────────────────────────────────────────┘
```

## Reproducibility guarantees

1. **Plan shape is schema-validated.** A YAML manifest that passes `master-plan.schema.json` is dispatchable; failure → fix the manifest, no plan-rot.
2. **Chunk-sizing is data-driven via rubric.** Same signals → same chunk count + budget — no hand-tuning.
3. **Fragment formats are schema-validated** at write time (by the chunk agent) AND at read time (by the merge step). Conflicts are impossible by construction (one writer per fragment file).
4. **Merge actions are an enumerated set** (see `merge-action.schema.json`). Custom merge logic = add an action to the enum + register a handler; no ad-hoc merge code.
5. **Ledger is JSONL append-only.** Each `(chunk_id, item_id)` ticks through `pending → in_progress → done|skipped|failed`. Resumable across agent handoffs.

## How to use

1. **Author the master plan** (`master-plan.yaml`) by hand, modeled on `examples/master-plan.example.yaml`.
2. **Validate:**
   ```bash
   python3 -c "
   import json, yaml, jsonschema
   plan = yaml.safe_load(open('master-plan.yaml'))
   schema = json.load(open('docs/superpowers/templates/parallel-branches/schemas/master-plan.schema.json'))
   jsonschema.validate(plan, schema)
   print('plan is valid')
   "
   ```
3. **Compute chunk sizing** (or accept the manifest's pre-computed `chunks[]`):
   ```bash
   kaizen-rubric eval \
     --rubric docs/superpowers/templates/parallel-branches/rubrics/chunk-sizing.yaml \
     --signals '{"total_items": 27, "per_axis_cost_k": 8, "agent_slots_available": 15, "token_budget_constrained": false, "tiers_used": 3}'
   ```
   → returns `bucket: GRID_15` + `confidence: 1.0`.
4. **Dispatch** per the manifest's `concurrency_mode`:
   - `full_parallel` → one message with N Agent() calls
   - `waves` → repeated waves of `wave_size`
   - `chain` → one Agent at a time, sequential
   - `sequential` → same as chain with N=1
5. **MERGE** runs the actions list (`merge.actions[]`) in declared order, in a single parent context. Each action has a known handler (`consolidate_perms` → `_atomic.atomic_write(plugin.json, ...)`, etc.).

## When to adopt

- ≥3 logical work units → use the kit
- Multi-project (≥2 repos) → mandatory (cross-repo isolation guarantees come free)
- ≥10 items → mandatory (manual dispatch becomes error-prone)
- ≤2 items / single-component refactor → skip; use plain `kaizen:tdd` instead

## Related

- `docs/superpowers/templates/chunk-plan-template.md` — prose template (this kit is its schema-driven sibling)
- `docs/superpowers/plans/2026-05-18-coverage-axes-dynamic-chunks.md` — 15-chunk grid (worked example)
- `docs/superpowers/plans/2026-05-18-coverage-axes-tier-chain.md` — tier chain (worked example, same kit, chain shape)
- `plugins/kaizen/skills/decision-rubric/SKILL.md` — the rubric pattern this kit uses
- `plugins/kaizen/skills/workflow/scripts/schema_cli.py::BucketWalker` — the runtime that walks `chunk-sizing.yaml`
