# Mode B split-file layout — worked example

```
mode-b-split/
├── README.md                ← this file
├── plan.yaml                ← thin manifest: header + orchestration + chunks: glob + merge: path
├── chunks/
│   ├── chunk-1.yaml         ← one full chunk (foundation AST)
│   └── chunk-15.yaml        ← cross-repo chunk (different project, no fragments)
├── merge.yaml               ← merge step config
└── ledger/                  ← runtime — written as chunks execute
    └── (empty in this example — populated at dispatch time)
```

## Why this layout

See `../../ON_DISK_LAYOUT.md` for the full analysis.

Short version: at ≥5 chunks the monolithic blob (Mode A) creates merge conflicts, large diffs, and 50k+ token reads to edit one chunk. Mode B isolates each chunk to its own file, matching the parallel-dispatch isolation.

## Files explained

- **`plan.yaml`** is the master manifest. It declares header (scope / projects / source) + orchestration shape (concurrency_mode / verification_cadence) + `chunks: "./chunks/*.yaml"` (a glob) + `merge: "./merge.yaml"` (a path). Validated against `../../schemas/master-plan.schema.json`.

- **`chunks/chunk-N.yaml`** is one chunk per file. Validated against `../../schemas/chunk.schema.json` independently — operators can edit/dispatch/validate one chunk without loading the rest. Two examples shown:
  - `chunk-1.yaml` — kaizen-md axis chunk with full Guide / Tasks / TDD code blocks (~110 lines)
  - `chunk-15.yaml` — cross-repo chunk (different project, `isolation: none`, no fragments — distinct shape)

- **`merge.yaml`** is the MERGE step config (parent-only). Sequential action list including consolidate/append/dispatch + retrofit + cross-pollinate. Validated against `../../schemas/master-plan.schema.json#/$defs/merge`.

- **`ledger/`** is RUNTIME state. Each chunk's `.chunks/<id>/ledger.jsonl` (written in its worktree as it executes) gets copied here after the chunk's branch merges to master. Gives plan-level progress visibility without parsing through the worktrees.

## Loader

The kit's `_plan_loader.py` (proposed — not yet shipped) normalizes Mode A and Mode B to the same in-memory shape:

```python
plan = load_plan(Path("plan.yaml"))
# plan["chunks"] is always a list of dicts after load_plan, regardless of whether
# the YAML was Mode A (inline array) or Mode B (glob resolved to N chunk files).
```

After normalization, the validator + dispatcher + rubric all operate uniformly.

## Validating this example

```bash
# Plan manifest validates as Mode B (chunks: glob, merge: path)
python3 -c "
import json, yaml, jsonschema
plan = yaml.safe_load(open('plan.yaml'))
schema = json.load(open('../../schemas/master-plan.schema.json'))
# Strip the chunks/merge \$ref (loader does this; we test the manifest shape only here)
schema['properties']['chunks']['oneOf'] = [{'type': 'string'}]
schema['properties']['merge']['oneOf']   = [{'type': 'string'}]
jsonschema.validate(plan, schema)
print('plan.yaml validates as Mode B manifest')
"

# Each chunk file validates against chunk.schema.json
python3 -c "
import json, yaml, jsonschema
from pathlib import Path
schema = json.load(open('../../schemas/chunk.schema.json'))
for f in sorted(Path('chunks').glob('*.yaml')):
    jsonschema.validate(yaml.safe_load(f.read_text()), schema)
    print(f'{f.name} validates against chunk.schema.json')
"
```

## When NOT to use Mode B

- Plan has ≤4 chunks → Mode A blob is simpler (1 file vs 6)
- Plan is throwaway / one-shot → Mode A is faster to author
- Operator is new to the kit → start with Mode A, migrate to Mode B when authoring pain hits
