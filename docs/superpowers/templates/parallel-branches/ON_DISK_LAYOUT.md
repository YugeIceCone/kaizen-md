# On-disk layout — monolithic blob vs split-file

## TL;DR

| Plan size       | Recommended mode | Why                                                             |
|-----------------|------------------|-----------------------------------------------------------------|
| 1-4 chunks      | **Mode A (blob)**| One file is more scannable; split overhead not worth it         |
| 5-20 chunks     | **Mode B (split)**| Authorship isolation matches dispatch isolation (1 chunk = 1 file) |
| >20 chunks      | **Mode B (split) + library** | Chunks become reusable templates pulled from a shared library  |

The schema supports both modes — `chunks:` can be either an inline array (Mode A) or a glob string pointing at chunk files (Mode B).

## Current state — Mode A (monolithic)

`master-plan.example.yaml` shows the inline form: every chunk's full content (header + guide + tasks + isolation contract + dispatch) lives inside one root YAML file.

```
docs/superpowers/plans/<plan-name>/
└── master-plan.yaml      ← 1 file, ~1,500 lines for a 15-chunk plan
```

**Pros:** one-file scan; no path resolution; trivial diff for tiny plans.
**Cons that show up at scale (≥5 chunks):**

- **Diff churn:** editing chunk-3 forces a diff in a 1,500-line file. Code review becomes "where in the file is the change?"
- **Merge conflicts:** two operators editing different chunks → merge conflict on the master plan file (the *opposite* of the parallel-safe guarantee we have at execution time).
- **Cognitive load:** loading the whole plan into context to edit one chunk wastes 80% of the read tokens.
- **No template reuse:** every plan re-authors common chunk shapes (rubric-axis chunks, MCP-mount chunks, cross-repo chunks) by copy/paste instead of `$ref`.
- **Validation cost:** a single 1,500-line YAML re-parses on every edit; per-chunk YAMLs validate independently.

## Mode B — split-file layout (recommended for ≥5 chunks)

```
docs/superpowers/plans/<plan-name>/
├── plan.yaml                    ← header + orchestration table + chunks: glob
├── chunks/
│   ├── chunk-1.yaml             ← one chunk per file (~100 lines avg)
│   ├── chunk-2.yaml
│   ├── chunk-3.yaml
│   ├── ...
│   └── chunk-15.yaml
├── merge.yaml                   ← merge step config (optional — can inline in plan.yaml)
└── ledger/                      ← RUNTIME state, written as chunks execute
    ├── chunk-1.jsonl            ← progress trace (.chunks/1/ledger.jsonl is the in-worktree write target;
    ├── chunk-2.jsonl              after branch merge, gets copied here for plan-level visibility)
    └── ...
```

### `plan.yaml` becomes a thin manifest:

```yaml
version: 1
date: "2026-05-18"
scope: "Drain remaining tier-1/2/3 coverage-axes + axis-runner + cross-repo wiring"
projects: ["~/workspace/kaizen-md", "~/workspace/semantic-search"]
source: "~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl"
concurrency_mode: "full_parallel"
verification_cadence: "per_chunk"
rubric: "../../templates/parallel-branches/rubrics/chunk-sizing.yaml"

chunks: "./chunks/*.yaml"        # ← GLOB — schema resolves each file as one chunk
merge:   "./merge.yaml"          # ← path to merge config (or inline {actions: [...]})
```

### Each `chunks/chunk-N.yaml` follows the per-chunk schema:

```yaml
id: "chunk-1"
title: "Foundation AST — naming + iron-law"
purpose: "2 small AST audits — fn-name verb-match + iron-law-per-feature rollup"
project: "kaizen-md"
deps: []
subagent: "kaizen-implementer"
isolation: "worktree"
worktree_branch: "chunk-1-ast-naming"
budget_tokens: 32000
owns:
  scripts:
    - "plugins/kaizen/skills/workflow/scripts/fn_name_quality.py"
    - "plugins/kaizen/skills/workflow/scripts/iron_law_per_feature.py"
  # ...
fragments: ["perms.json", "progress.md"]
guide:
  # ...
tasks:
  - id: "1.A"
    # ...
```

Validates against `chunk.schema.json` (per-chunk, no plan-level keys).

### Trade-offs (Mode B)

**Pros:**
- **Authorship isolation matches dispatch isolation.** Operator-A edits `chunk-3.yaml`; operator-B edits `chunk-7.yaml`. Zero conflicts.
- **Templated reuse.** A `chunk-template.axis-coverage.yaml` can be copied + customized per axis, dropping the per-chunk YAML to ~30 lines.
- **Per-chunk validation.** `jsonschema chunks/chunk-3.yaml` works standalone.
- **Operator picks slice.** Subagent dispatch can read JUST its `chunks/chunk-N.yaml` (5k tokens) instead of the whole 1,500-line plan (50k tokens). **~10× setup token savings.**
- **Ledger location is symmetric.** Runtime ledger lives at `<plan>/ledger/chunk-N.jsonl` after branch merge; mirrors the plan-time chunk file.

**Cons:**
- More files (15 chunks → 17+ files vs 1)
- Need a kit-aware loader that resolves `chunks: "<glob>"`
- Path resolution rules (relative-to-plan-file)

## Loader contract (resolves Mode A or Mode B uniformly)

The kit's loader normalizes both modes to the same in-memory shape:

```python
# plugins/kaizen/skills/workflow/scripts/_plan_loader.py (proposed)
def load_plan(path: Path) -> dict:
    """Load a master plan, resolving chunks: glob if present."""
    plan = yaml.safe_load(path.read_text())
    if isinstance(plan.get("chunks"), str):
        # Mode B — glob to files
        chunk_dir = path.parent
        chunk_files = sorted(chunk_dir.glob(plan["chunks"].removeprefix("./")))
        plan["chunks"] = [yaml.safe_load(f.read_text()) for f in chunk_files]
    if isinstance(plan.get("merge"), str):
        merge_path = path.parent / plan["merge"].removeprefix("./")
        plan["merge"] = yaml.safe_load(merge_path.read_text())
    return plan
```

After this normalization, the rest of the kit (validator, rubric, dispatcher) is mode-agnostic.

## Library extension — shared chunk templates (for ≥20-chunk plans)

```
docs/superpowers/templates/parallel-branches/
├── chunks-library/                  ← NEW reusable chunk templates
│   ├── axis-coverage-chunk.template.yaml
│   ├── retrofit-chunk.template.yaml
│   ├── cross-repo-chunk.template.yaml
│   └── mcp-mount-chunk.template.yaml
└── ...
```

Each template is a chunk file with `${...}` placeholders for the customizable bits (axis name, brainstorm refs, exemplar paths). A plan composes its chunks by:

```yaml
# plan.yaml
chunks:
  - $template: "axis-coverage-chunk"
    vars:
      axis_name: "fn_name_quality"
      brainstorm_ref: "10"
      exemplars: ["class_name_quality.py"]
  - $template: "axis-coverage-chunk"
    vars:
      axis_name: "iron_law_per_feature"
      # ...
```

Reduces a 15-chunk plan from ~1,500 lines of inline chunks to ~100 lines of template invocations. Out of scope for the v1 kit — implement when ≥3 plans demonstrate the same chunk shape (DRY trigger).

## Concrete recommendation for the current coverage-axes plans

The 3 plans we've shipped (5-chunk / 15-chunk / tier-chain) are all in **Mode A as markdown prose docs**. They're not YAML-validated, so the schema kit doesn't apply to them today. To benefit:

1. **For active plans** (the 15-chunk dynamic-chunks plan): keep the markdown prose form for human reading; ALSO emit a YAML form at `plans/<plan-name>/plan.yaml` + `chunks/chunk-N.yaml` for schema validation + dispatcher consumption. Markdown for humans, YAML for tooling.
2. **For new plans**: start in Mode B directly (split YAML files). The markdown prose form becomes optional — generated from the YAML via a small renderer.

## Migration path (when ready)

| Stage | Action |
|-------|--------|
| Today | Mode A works (1 YAML file per plan); kit fully validates                   |
| Next  | Add `_plan_loader.py` that resolves `chunks: "<glob>"` (≤50 lines stdlib) |
| Then  | Add per-chunk `chunk.schema.json`; existing inline-array form still valid |
| Then  | Migrate the worked-example plan to Mode B as proof                         |
| Later | Add `chunks-library/` templates when DRY triggers fire (3rd plan with same chunk shape) |

This file is the spec for those stages. No code changes in this commit — analysis + recommendation only.

## Summary table

| Layout option | Files | Best fit | Schema impact |
|---|---|---|---|
| Mode A — monolithic blob | 1 YAML | ≤4 chunks; one-shot plans | Current schema works |
| Mode B — split files | N+2 (plan + chunks/ + merge) | 5-20 chunks; multi-operator plans | Add `chunks: "<glob>"` to root schema + add `chunk.schema.json` |
| Mode B + library | N+2 + shared templates | ≥20 chunks; many similar plans | Add `$template` indirection + var substitution |
