# The optimal parallel-branches system — synthesis

> **Disciplines:** all rules in `DISCIPLINES.md` apply. See D1 (explicit info), D2 (floor), D3 (line caps) especially. This synthesis honors all 10 disciplines.

Distilled from this session: BK-012 spec → 30-axis coverage loop → chunk-plan template → schema-driven kit → on-disk layout analysis → plan-level ledger+checklist → pre-dispatch audit → wave-mode walkthrough → chunking floor → line-based work orders.

## Design goals

| Goal                                            | Why                                                                       |
|-------------------------------------------------|---------------------------------------------------------------------------|
| **Reproducible from declaration alone**         | Same YAML → same dispatch, regardless of who runs it                       |
| **Parallel-safe by construction**               | No two agents ever write the same canonical file (compile-time guarantee) |
| **Scales 1 → 50 chunks linearly**               | One mechanism handles 5 chunks AND 50 — no mode-switch                    |
| **Token-frugal**                                | Each agent reads ~5k of plan context (not 50k)                             |
| **Resumable across failures + handoffs**        | Ledger-driven; failed wave doesn't void prior waves                       |
| **Operator runbook = ≤6 commands**              | Tooling absorbs the ritual; cognition spent on work                       |

## Hard design choices (lock these in)

0. **Chunking floor is non-negotiable: 2-3 items per subagent** (see `CHUNKING_FLOOR.md`). Below floor = setup waste. Routing tree: **≤3 items total → parent does it (no dispatch)**; **4-6 items → one subagent (no chunking)**; **7-30 items → `ceil(N/3)` chunks**; **30+ items → queue-picker pool**. This is choice #0 because it gates every decomposition that follows. If the rubric returns `PARENT_DOES_IT`, NONE of the choices below apply — work happens in the parent.

1. **Wave mode is the default** (when decomposition IS justified). `concurrency_mode: "waves"`, `wave_size: 5`. Even "small" 5-chunk plans use one wave — uniform shape beats mode-switching. Full-parallel and chain are special cases of N=1 wave and 1-per-wave respectively.

2. **Mode B (split files) always.** No Mode A blob option in the recommended path. One chunk per file from day one, even for tiny plans. Uniformity > one-file convenience.

3. **Two merge stages, mandatory.** `interwave` (fragment consolidation + checklist refresh) + `final` (retrofit + cross-pollinate + cleanup + commit + verify). Even single-wave plans run both — the interwave-after-wave-1 is a no-op for retrofit/x-pollinate but keeps the shape uniform.

4. **Single plan-level ledger (`MASTER.jsonl`).** Per-chunk worktree ledgers append into MASTER on branch merge. Renderer reads ONE file, not 20.

5. **Live CHECKLIST.md regenerated on every merge action.** Always reflects current state. Markdown for human eyes, derived from MASTER.jsonl + chunks/*.yaml.

6. **One CLI surface: `kaizen-plan`.** Six subcommands: `init / check / dispatch / merge / status / cleanup`. No proliferation.

7. **YAGNI on chunk-library / `$template` indirection.** Defer until ≥3 plans demand the same shape (DRY trigger).

8. **Default `failure_policy: "partial"`.** Wave proceeds with successes; failed chunks file backlog parks for follow-up. Aborting the whole plan on one failure is too coarse.

9. **Work-order size in LINES not tokens (D3).** Default `max_lines: 150` (≈ 2-3 items at floor with TDD snippets); hard cap `200`. `items_count` declared explicitly per chunk. Token budgets dropped entirely — too abstract, varied by content density. Lines are concrete + measurable + visible at-a-glance. Validator warns above hard cap.

10. **Conflict pre-flight is non-negotiable.** `kaizen-plan check` runs before every `dispatch` and `merge` invocation. Silent collisions are the worst failure mode. **Also enforces the floor** — flags sub-2-item chunks.

## Complete on-disk layout

```
~/workspace/<repo>/docs/superpowers/plans/<plan-name>/
├── plan.yaml                        ← thin manifest (header + chunks: glob + merge: path + ledger_dir + checklist)
├── chunks/
│   ├── chunk-01.yaml                ← one per chunk; zero-padded id for stable sort
│   ├── chunk-02.yaml
│   ├── ...
│   └── chunk-20.yaml
├── merge.yaml                       ← stages: {interwave: [...], final: [...]}
├── ledger/
│   ├── MASTER.jsonl                 ← single append-only consolidated ledger
│   └── (per-chunk archive — auto-pruned after final merge)
└── CHECKLIST.md                     ← generated; always current; markdown
```

## plan.yaml (the manifest)

```yaml
version: 1
date: "2026-MM-DD"
scope: "<one-line — what this plan delivers>"
projects:
  - "~/workspace/repo-a"
  - "~/workspace/repo-b"            # optional — multi-project
source: "<path/to/brainstorm.jsonl>"

decomposition:
  rubric: "<path-to-chunk-sizing.yaml>"
  bucket: "GRID_15"                 # populated by `kaizen-plan size`; traceability
  total_items: 27
  per_axis_cost_k: 8
  total_lines_estimate: 1800        # auto-computed: sum(chunks.max_lines); operator sanity check

concurrency:
  mode: "waves"                     # always; single-wave plans are just N=1
  wave_size: 5
  failure_policy: "partial"          # partial | abort | defer

chunks:    "./chunks/*.yaml"        # glob (Mode B always)
merge:     "./merge.yaml"           # always external

ledger_dir: "./ledger/"
checklist:  "./CHECKLIST.md"
```

## chunks/chunk-NN.yaml (one per chunk)

```yaml
id:                "chunk-01"
wave:              1                 # explicit wave assignment; dep-checked
title:             "<title>"
purpose:           "<one line>"
project:           "kaizen-md"
deps:              []                # ids of chunks that must finish first
subagent:          "kaizen-implementer"
isolation:         "worktree"
worktree_branch:   "chunk-01-ast-naming"
max_lines:         150               # D3 default; hard cap 200
items_count:       2                 # D2 floor: 2-3 items per chunk
design_heavy:      false             # set true for legitimately-1-item chunks (bypasses floor check)

owns:
  scripts:        ["plugins/kaizen/skills/.../foo.py"]
  tests:          ["plugins/kaizen/tests/test_foo.py"]
  bins:           ["plugins/kaizen/bin/kaizen-foo"]
  fragment_dir:   ".chunks/01/"

fragments:        ["perms.json", "progress.md"]

guide:
  working_dir: "/home/cherry86/workspace/kaizen-md"
  skills_to_load: ["kaizen:tdd", "kaizen:plugin-development"]
  exemplar_files: ["plugins/kaizen/skills/.../class_name_quality.py"]
  conventions: ["...", "..."]
  upstream_decisions: ["..."]
  do_not_touch: ["vendored skills", "gateway.py::SUBSERVERS"]

tasks:
  - id: "1.A"
    brainstorm_ref: "10"
    description: "<one-line>"
    red_test_snippet: |
      <pytest snippet>
    green_outline: |
      <bullets: api / algorithm / reuses>
    commit_message: "feat(foo): <one-line> (chunk 01 item A)"
  - id: "1.B"
    # ...
```

## merge.yaml (staged)

```yaml
run_by: "parent"

stages:
  # Runs after every wave (including the last — uniform shape)
  interwave:
    max_lines: 100      # interwave merge.yaml stays terse
    actions:
      - consolidate_perms           # merge .chunks/<wave-ids>/perms.json → plugin.json
      - append_progress             # cat .chunks/<wave-ids>/progress.md → progress.md
      - dispatch_backlog            # kaizen backlog add for each .chunks/<wave-ids>/backlog.jsonl row (dedupe by title+ref)
      - render_master_ledger        # cat .chunks/<wave-ids>/ledger.jsonl → ledger/MASTER.jsonl
      - render_checklist            # walk chunks/*.yaml + ledger/MASTER.jsonl → CHECKLIST.md
      - cleanup_merged_worktrees    # rm worktrees for wave-N branches that landed on master

  # Runs ONCE after the final wave
  final:
    max_lines: 200      # final merge action list can be larger
    actions:
      - wire_mcp_mounts             # gateway.py::SUBSERVERS += .chunks/*/mcp-mounts.txt
      - action: retrofit
        targets: ["md_whitespace", "md_dupes", "md_heading_depth", "todo_inventory", "unused_env"]
      - action: cross_pollinate
        to_project: "~/workspace/semantic-search"
        axes: ["fn-name-quality", "validator-wiring", "trace-bloat-join"]
      - cleanup_fragments           # rm -rf .chunks/
      - merge_commit
      - final_verify
      - render_checklist            # final refresh — includes retrofit + x-pollinate state
```

## The 6 runtime pieces (minimum viable system)

| Piece | LOC est | Why critical |
|---|---|---|
| `_plan_loader.py` | ~80 | Resolves `chunks: glob` + `merge: path` to in-memory dicts |
| `_plan_check.py` | ~150 | Cross-chunk uniqueness (owns, worktree_branch, fragment_dir) + dep-cycle + wave-dep order |
| `_plan_dispatch.py` | ~200 | Per-wave Agent() prompt generation + worktree creation + wait barrier |
| `_merge_handlers.py` | ~300 | One handler per merge action; staged invocation |
| `_plan_render.py` | ~150 | MASTER.jsonl + chunks/*.yaml → CHECKLIST.md |
| `_plan_cli.py` | ~100 | argparse dispatcher for the 6 subcommands |

**Total: ~980 LOC.** Lives at `plugins/kaizen/skills/parallel-branches/scripts/` once landed.

Plus the canonical 7 schemas + 1 rubric (already shipped this session) + tests for each runtime piece (TDD per kaizen discipline).

## Operator runbook (≤6 commands)

```bash
# 1. Init — scaffold plan dir from rubric output
kaizen-plan init --rubric chunk-sizing.yaml --signals '{"total_items": 27, ...}' \
    --out docs/superpowers/plans/2026-MM-DD-foo/
# → writes plan.yaml + chunks/chunk-01.yaml ... chunk-NN.yaml (one per item) + merge.yaml

# 2. Edit chunk files (one per file — operator's main task)
# (manual — write Guide / Tasks per chunk per the chunk.schema.json shape)

# 3. Pre-flight check (catches collisions before dispatch)
kaizen-plan check --plan plan.yaml
# ✓ schemas valid, ✓ no ownership collisions, ✓ no dep cycles, ✓ wave deps respected

# 4. Per-wave loop (dispatcher handles the ritual)
for wave in 1 2 3 4; do
    kaizen-plan dispatch --plan plan.yaml --wave $wave
    # → spawns 5 Agent() calls in parallel, waits for all 5, merges branches to master
    kaizen-plan merge --plan plan.yaml --stage interwave
done

# 5. Final merge
kaizen-plan merge --plan plan.yaml --stage final

# 6. Status (run anytime to see CHECKLIST.md state)
kaizen-plan status --plan plan.yaml
```

**6 commands total** for a 20-chunk × 4-wave plan. The `for` loop is one logical step; `init` + `check` + `final` + `status` are the others.

## Decision rationale (why this shape over alternatives)

| Choice | Alternative considered | Why this won |
|---|---|---|
| Mode B always | Mode A blob for small plans | Cognitive uniformity > one-file convenience; same loader code works for 5 or 50 chunks |
| Wave mode default | Full-parallel default | Anthropic slot limits favor 5-10 concurrent; wave is the safe default — full-parallel is just `wave_size: N` |
| Two-stage merge | Single flat merge | Inter-wave consolidation enables progress visibility + cleanup; final-only would defer dashboard until plan-end |
| Single MASTER.jsonl | Per-chunk ledger files at plan level | One render input vs N — checklist generator is simpler |
| Default budget 30k | Min (20k) / Max (40k) | Mid-range gives retry headroom; chunks rarely fit exactly at the cap |
| `failure_policy: partial` | `abort` (today's behavior — implicit) | Aborting a 20-chunk plan because 1 failed is too coarse; partial fits the brainstorm-driven nature of the work |
| Single `kaizen-plan` CLI | Multiple top-level bins | One mental surface; subcommands signal intent (`init/check/dispatch/merge/status/cleanup`) |
| Defer chunk library | Build now | YAGNI — wait for ≥3 plans with shared shape (DRY trigger) |
| `wave:` field per chunk | Implicit ordering by chunk-id | Explicit dep-checking catches mis-assigned chunks |

## Migration path (from current state to optimal)

```
PHASE 1 — runtime foundation (BEFORE any 20-chunk plan)
  ├─ Build _plan_loader.py (resolves Mode B globs)            ~80 LOC
  ├─ Build _plan_check.py (cross-chunk validators)            ~150 LOC
  ├─ Build _merge_handlers.py — start with:                   ~150 LOC
  │   - consolidate_perms
  │   - append_progress
  │   - render_master_ledger
  │   - render_checklist
  ├─ Wire kaizen-plan CLI shell (check + status commands)     ~50 LOC
  └─ Paired tests for each module

PHASE 2 — dispatch + remaining handlers
  ├─ Build _plan_dispatch.py — per-wave Agent prompt gen      ~200 LOC
  ├─ Worktree orchestration (create + cleanup-merged)         ~80 LOC
  ├─ Remaining merge handlers (retrofit / cross_pollinate /   ~150 LOC
  │   wire_mcp_mounts / cleanup_fragments / merge_commit /
  │   final_verify / dispatch_backlog)
  └─ kaizen-plan {init, dispatch, merge, cleanup} subcommands

PHASE 3 — wave-mode polish
  ├─ failure_policy enforcement (partial/abort/defer)
  ├─ wave dep checker (chunk-N's deps must be in earlier waves)
  ├─ wave-progress section in CHECKLIST.md render
  ├─ Auto-handoff parentage (parent_chunk_id ledger field)
  └─ Pre-dispatch token-budget aggregation (warn if > total)

PHASE 4 — quality of life (later, when DRY triggers fire)
  ├─ kaizen-plan render-dag (mermaid)
  ├─ chunks-library/ + $template indirection
  ├─ multi-rubric support (size by tier vs by domain vs by budget)
  └─ Web dashboard for CHECKLIST.md
```

**Stop at Phase 2** for the minimum 20-chunk × 4-wave system. Phases 3-4 are improvements, not blockers.

## What this synthesis does NOT solve

Honesty checklist:

- ❌ **Subagent skill-load duplication** — each of 20 agents loads `kaizen:tdd` + `kaizen:plugin-development` independently. ~280k tokens wasted per plan. Fix requires kaizen-implementer subagent system-prompt baking (out of scope for this kit).
- ❌ **Disk consumption** — 20 worktrees × ~500MB = 10GB. `cleanup_merged_worktrees` reclaims after each wave but the peak is real.
- ❌ **Cross-repo MCP mounting** — chunk 15 in semantic-search can't easily inject MCP servers into kaizen-md (gateway.py is kaizen-md-side). Workaround: cross-repo chunks file backlog parks instead of doing the MCP wiring.
- ❌ **Concurrent operator edits** — two humans editing chunks/*.yaml at the same time still git-merge-conflict in the chunk files (just like any source). Mode B reduces blast radius but doesn't eliminate conflicts.
- ❌ **Brainstorm freshness** — if the source brainstorm changes mid-plan, the rubric output may shift; current design has no "plan needs re-sizing" detector.

## End-to-end size estimate (line-based per D3)

**For a 9-chunk × 3-wave plan (the 27-item coverage scope at the FLOOR per D2):**

| Component | Lines authored |
|---|---|
| `plan.yaml` manifest | ~50 |
| 9 × `chunks/chunk-NN.yaml` (3 items each at floor) | 9 × ~130 = ~1170 |
| `merge.yaml` (staged) | ~80 |
| `ledger/MASTER.jsonl` runtime (grows during execution; ~5 rows/item × 27 = ~135 rows) | ~135 |
| `CHECKLIST.md` generated | ~100 |
| **TOTAL authored content** | **~1,535 lines** |
| **TOTAL inclusive of runtime** | **~1,670 lines** |

Each agent reads at most ONE chunk file (~130 lines) + template (~280 lines) + 1-2 exemplars. Subagent input ≤ ~800 lines total per dispatch — well within reasonable context.

This replaces the prior token-budget table (D3 dropped tokens entirely — lines are concrete + visible at-a-glance; tokens were too abstract).

## TL;DR

The optimal system is the kit we built this session, **plus** ~980 LOC of runtime (6 modules) in a single `plugins/kaizen/skills/parallel-branches/` skill, **with** the wave-mode polish from `WAVE_DISPATCH_WALKTHROUGH.md`. Operator surface collapses to 6 commands. Same shape scales from 5 chunks to 50.

**Start point for implementation:** Phase 1 of the migration path. ~430 LOC. After that, real 20-chunk × 4-wave plans become tractable. Until then, the kit is a strong spec that operators hand-fake.
