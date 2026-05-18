# Work pool — agents pick items, sequential picking

> ⚠️ **SUPERSEDED** by [`QUEUE_PICKER_BRAINSTORM.md`](QUEUE_PICKER_BRAINSTORM.md). The atomic-rename pool design here is more complex than the simpler "parent-as-xargs" pattern. Kept for historical context.
> **Disciplines:** all rules in [`DISCIPLINES.md`](DISCIPLINES.md) apply.

> User idea sharpened: "shared work pool, agent picks work, picking happens sequentially"

A different shape from the coordination pool (`SHARED_POOL_BRAINSTORM.md`). That added inter-agent messaging on top of pre-assigned chunks. This re-imagines dispatch itself: **no pre-assigned chunks** — agents are generic workers that pick from a shared queue. Picking is serialized (atomic), execution is parallel.

## Why this changes the architecture

Current chunk-based:
- Master plan → N pre-sized chunks → N agent slots, each tied to its chunk for life
- Fast agents idle when their chunk finishes early (waiting for siblings, waiting for next wave)
- Slow chunks bottleneck the wave (must wait for the longest to finish before merge)
- Failed chunk has its agent slot wasted (returns nothing to merge)
- Rubric must size chunks correctly (hard — workload varies)

Work-pool based:
- Master plan → flat list of items in a pool → fixed-N agent slots, generic workers
- Agent finishes item → picks next from pool → no idle time
- Slow items don't bottleneck — other agents keep picking
- Failed items go back to pool (or to failed/) — operator decides retry; agent moves on
- No chunk-sizing — rubric only decides POOL SIZE (5 workers vs 10 vs 20)

The chunk-based model treats agents as long-running owners of a slice; the work-pool model treats them as ephemeral processors of one item at a time.

## On-disk layout

```
docs/superpowers/plans/<plan-name>/
├── plan.yaml                        ← concurrency.mode: "work_pool"
├── pool/
│   ├── pending/                     ← items waiting to be picked
│   │   ├── item-001.yaml
│   │   ├── item-002.yaml
│   │   └── ...
│   ├── claimed/                     ← items currently being worked
│   │   └── item-007.yaml            ← claimed by agent slot-3 at T+12min
│   ├── done/                        ← shipped + committed
│   │   ├── item-003.yaml
│   │   └── ...
│   ├── failed/                      ← failed; operator triage
│   │   └── item-005.yaml
│   └── blocked/                     ← unmet deps; waiting
│       └── item-012.yaml
├── ledger/
│   ├── MASTER.jsonl
│   └── SHARED/                      ← optional coordination pool (separate concern)
└── CHECKLIST.md
```

Items move between directories via **atomic rename** (`os.rename` / `git mv`). Filesystem guarantees on POSIX: only one of two concurrent renames succeeds; the other gets `ENOENT`. **This is the entire pick mechanism — no locks, no SQLite, no protocol.**

## Item schema (replaces chunk schema)

Smaller than chunk — items are leaf work units:

```yaml
# pool/pending/item-001.yaml
id:              "item-001"
brainstorm_ref:  "10"
title:           "kaizen-fn-name-quality"
project:         "kaizen-md"
deps:            []                   # other item ids that must be in done/ first
budget_tokens:   8000                 # ~6-10k per single-axis item

owns:
  scripts:       ["plugins/kaizen/skills/.../fn_name_quality.py"]
  tests:         ["plugins/kaizen/tests/test_fn_name_quality.py"]
  bins:          ["plugins/kaizen/bin/kaizen-fn-name-quality"]
  fragment_dir:  ".chunks/item-001/"

guide:
  skills_to_load: ["kaizen:tdd", "kaizen:plugin-development"]
  exemplar_files: ["plugins/kaizen/skills/.../class_name_quality.py"]

task:
  description:      "AST: function names start with verb"
  red_test_snippet: |
    def test_get_user_starts_with_verb(self):
        ...
  green_outline: |
    AST walk top-level FunctionDefs; verb-prefix list.
  commit_message: "feat(fn-name-quality): AST verb check (item-001)"
```

One item = one TDD unit (RED → GREEN → commit). Way smaller scope than the current chunks. The 30-item shape replaces the 15-chunk-each-doing-2-items shape, but the WORK IS THE SAME.

## Picking protocol (sequential by filesystem atomicity)

Each worker agent runs this loop:

```python
def worker_loop(worker_id: str, pool: Path):
    while True:
        item = pick_next(pool, worker_id)
        if item is None:
            return  # pool empty — worker exits gracefully

        try:
            execute_item(item, worker_id)
            release_done(item)
        except Exception as e:
            release_failed(item, error=str(e))
            continue  # pick next; failure doesn't kill the worker

def pick_next(pool: Path, worker_id: str) -> Item | None:
    """Atomic claim — returns the first pendable item that:
       1. Is in pool/pending/
       2. Has all deps satisfied (deps in pool/done/)
       3. We successfully renamed to pool/claimed/
    """
    for item_path in sorted(pool.glob("pending/*.yaml")):
        item = load_item(item_path)
        if not deps_satisfied(item, pool):
            move_to_blocked(item_path)  # comes back to pending when deps clear
            continue
        target = pool / "claimed" / item_path.name
        try:
            os.rename(item_path, target)  # ATOMIC — only one worker wins
        except FileNotFoundError:
            continue  # another worker beat us; try next item
        write_claim_marker(target, worker_id)
        return load_item(target)
    return None  # nothing pickable
```

**This is the whole "sequential picking" mechanism.** Python `os.rename` on POSIX is atomic; if 5 workers race, exactly 1 succeeds for any given item. No coordination needed beyond the filesystem.

### Why filesystem rename instead of SQLite / fcntl

- **KISS** — `os.rename` is one line; SQLite is ~300 LOC of schema + connection + transaction
- **Inspectable** — `ls pool/pending/ pool/claimed/ pool/done/` shows full state immediately
- **Resumable** — kill all workers, restart later; state is on disk in obvious form
- **Git-trackable** — `git status pool/` shows what got claimed in this session
- **No daemon needed** — pure stdlib

### Worker idempotency (the only real complication)

If worker-2 dies after `pool/claimed/item-007.yaml` rename but before `pool/done/`, item-007 is stuck in `claimed/`. Recovery:

```bash
kaizen-plan pool reap --max-age 30min
# Moves items from claimed/ back to pending/ if their claim marker is older than --max-age
# (the claim marker = a sidecar file `.claim.<worker_id>.<ts>` written at claim time)
```

Operator runs `reap` between waves or on demand. Agents on restart see fresh `pending/` items.

## Dep resolution

Items with unmet deps move to `blocked/`. Periodically (every N seconds or on each pick), the runtime checks `blocked/` items and promotes any whose deps are now in `done/` back to `pending/`. No coordination needed — the next picking worker sees them.

Simpler alternative: deps are checked at pick time only. If unmet, return item to `pending/` and try the next. This works as long as workers don't infinite-loop checking the same items. Trivially prevented by a per-worker bloom of "items I've recently passed on".

## Integration with concurrency modes

Work pool **replaces** wave/chunk batching but **composes** with everything else in the kit:

| Existing kit feature                          | Work-pool mode |
|-----------------------------------------------|----------------|
| Mode B split files                            | Re-used — items are files, just in `pool/` subdirs instead of `chunks/` |
| Fragment writes (`.chunks/item-NNN/`)         | Re-used; one fragment dir per item |
| Plan-level ledger + checklist                 | Re-used; checklist now shows item-state (pending/claimed/done/failed/blocked) |
| Merge stages                                  | Re-used; same consolidation logic |
| Isolation contract                            | Re-used; each item declares its `owns:` |
| Worktree per worker (not per item)            | NEW — worktree is associated with a worker slot, reused across items |
| `concurrency.mode: "work_pool"`               | NEW — replaces "waves" / "chain" / "full_parallel" |
| `concurrency.pool_size: 5`                    | NEW — number of worker agents |
| Wave concept                                  | OPTIONAL — work_pool can be wave-bounded (run pool for one wave duration / budget, then merge, then restart workers for next wave) |

## Token cost comparison

For the 27-item coverage-axes example:

| Mode | Setup cost | Per-item cost | Total tokens |
|---|---|---|---|
| 15-chunk grid (current) | 15 × 15k (skill loads + exemplar reads) = 225k | ~8k × 27 items | ~225k + 216k = **441k** |
| Work pool (5 workers, 27 items) | 5 × 15k = 75k (one setup per WORKER, not per item) | ~8k × 27 items | ~75k + 216k = **291k** |

**~35% token savings** because skill loads are amortized over many items per worker (each worker picks ~5-6 items).

## Failure handling shape

Worker hits an issue on item-005:

```python
try:
    execute_item(item-005)
except TestFailedError as e:
    # Move to failed/ with diagnostic
    item.error = str(e)
    item.partial_commits = [...]   # SHAs of any committed work
    move_to_failed(item)
    continue  # worker doesn't die; picks next item
```

After plan run:
- `ls pool/failed/` — operator triage
- Edit failed item (fix RED test, refine GREEN outline, etc.) → mv back to `pending/`
- Re-spawn one worker → it picks the formerly-failed item, retries
- Or: `kaizen-plan pool retry --failed-only` re-runs

**Critical:** failure isolation is per-item not per-worker. One bad item doesn't kill the worker (which would lose all its accumulated context).

## Wave-mode + work-pool composition

Wave is a TIME / BUDGET bound on pool execution:

```yaml
# plan.yaml
concurrency:
  mode: "work_pool"
  pool_size: 5
  waves:
    - {budget_tokens: 150000, max_duration: "45min"}   # wave 1 — workers run until budget hit
    - {budget_tokens: 150000, max_duration: "45min"}   # wave 2
    - {budget_tokens: 150000, max_duration: "45min"}   # wave 3
    - {budget_tokens: 150000, max_duration: "45min"}   # wave 4
```

Each wave: spawn 5 workers, they pick from pool until wave budget exhausted, then merge interwave, then next wave spawns fresh 5 workers (re-using pool — picking up where prior wave left off).

OR: wave-less mode — `pool_size: 5` workers run continuously until pool empty.

The wave bound is useful when:
- Plan-level token budget needs phased pacing (avoid burning whole budget in one shot)
- Inter-wave merges add value (consolidation between phases)
- Operator wants to inspect state between waves

Wave-less is useful when:
- One-shot dispatch where the plan ships in one go
- Smaller pools (<30 items) where merge-once-at-end is fine

## What the rubric becomes

Work-pool mode changes the rubric purpose:

| Old rubric (chunk-sizing) | New rubric (worker-sizing) |
|---|---|
| "How many chunks?" | "How many concurrent workers?" |
| Signals: total_items, per_chunk_cap, slots_available | Signals: total_items, per_item_cost, agent_slots_available, plan_budget |
| Output: bucket = GRID_5 / GRID_15 / TIER_CHAIN | Output: pool_size = 5 / 10 / 20 + wave_count = 1 / 2 / 4 |

`chunk-sizing.yaml` would become `worker-sizing.yaml` with simpler signals and outputs.

## Pros / cons table

| Concern | Chunk-based (current) | Work-pool (proposed) |
|---|---|---|
| **Load balancing** | Manual via chunk-sizing rubric | Automatic — fast agents pick more |
| **Idle slots** | Common (waves wait for slowest) | None (workers always picking) |
| **Failure blast radius** | Whole chunk lost on agent crash | Just the in-flight item; worker continues |
| **Setup token cost** | High (skill loads per chunk agent) | Low (one setup amortized per worker over many items) |
| **Rubric complexity** | High (chunk size + dep ordering + wave assignment) | Low (just pool size) |
| **Coordination** | None (chunks pre-assigned) | Sequential pick (filesystem rename) |
| **Item-level resumability** | All-or-nothing per chunk | Per-item — fine-grained restart |
| **Dep handling** | Implicit via wave ordering | Explicit per-item deps + blocked/ dir |
| **Pre-flight check value** | Catches ownership collisions | Same — still mandatory |
| **Operator visibility** | Per-chunk CHECKLIST | Per-item directory state (`ls pool/`) |
| **Per-item context overhead** | Low (chunk holds context across items) | Higher (each item is its own RED→GREEN cycle in same worker, but item context grows) |
| **Mental model** | "Plan = 15 chunks" | "Plan = 27 items + 5 workers" |
| **Schema rework** | None | Item replaces chunk; pool/ replaces chunks/ |

## When work-pool wins, when chunk-based wins

**Work-pool wins when:**
- Items vary significantly in difficulty (load balancing matters)
- Failure tolerance is critical (one bad item shouldn't waste an agent)
- Total items >>> total workers (e.g. 100 items, 5 workers)
- Items are mostly independent (few cross-item deps)
- Operator wants fine-grained resume (restart from item N+1, not "redo the whole chunk")

**Chunk-based wins when:**
- Items are tightly grouped (chunk-1's 3 items share state / build on each other)
- Each chunk needs distinct setup (different skills, different exemplars per chunk)
- Operator wants to reason about coherent units (chunk = milestone)
- Items have heavy inter-item deps within a chunk (chunk's commit cadence matters)

**Hybrid (the realistic answer):**
- Pool-mode for the LARGE bulk of repeatable items (axes, simple TDD units)
- Chunk-mode for the FEW design-heavy items (axis-runner #161 — needs a long-running coherent context)
- Plan declares both: `pool: ./pool/` (items) + `chunks: ./chunks/` (design-heavy)

## Concrete sketch for the coverage-axes plan

Re-rendered as work-pool mode:

```
docs/superpowers/plans/2026-05-18-coverage-axes-pool/
├── plan.yaml                                  ← pool_size: 5, waves: 4 × budget
├── chunks/                                    ← reserved for design-heavy items
│   ├── chunk-axis-runner.yaml                 ← #161 — needs long-running context
│   └── chunk-cross-repo.yaml                  ← chunk 15 cross-repo
├── pool/
│   ├── pending/
│   │   ├── item-001-fn-name-quality.yaml      ← #10
│   │   ├── item-002-validator-wiring.yaml     ← #18
│   │   ├── item-003-mock-real-pairing.yaml    ← #23
│   │   ├── ...                                ← all 23 tier-1/2/3 axes that fit the simple shape
│   ├── claimed/
│   ├── done/
│   ├── failed/
│   └── blocked/
├── merge.yaml                                 ← stages: interwave + final
├── ledger/
└── CHECKLIST.md
```

Workflow:
1. `kaizen-plan init --pool` generates 23 item files + 2 chunk files (the design-heavy ones)
2. `kaizen-plan check` validates pool items + chunks
3. Wave 1: spawn 5 workers (pool) + 2 dedicated agents (chunks) = 7 parallel. Workers pick from `pool/pending/`; chunks run their long-form work.
4. Workers finish their wave's budget; chunks finish on their own pace. Interwave merge consolidates.
5. Wave 2: re-spawn 5 workers; chunks already done, no re-spawn needed for them.
6. Continue until `pool/pending/` empty.
7. Final merge.

## Runtime additions (delta from chunk-based runtime)

| New module | LOC | Purpose |
|---|---|---|
| `_pool_picker.py` | ~80 | Atomic rename, dep-check, blocked/ promotion |
| `_pool_worker.py` | ~120 | Worker loop, idempotency, failure-isolation |
| `_pool_init.py` | ~80 | Split master items list into `pool/pending/*.yaml` files |
| `_pool_reap.py` | ~60 | Reaps stuck `claimed/` items past --max-age |
| `_pool_status.py` | ~40 | `ls`-like view of pool state for CHECKLIST.md |

**Total: ~380 LOC.** Plus item.schema.json (small).

Composes with the existing 980 LOC of chunk-based runtime (from `OPTIMAL_SYSTEM.md`) — work-pool is additive, not replacement. Operator picks mode per plan.

## New gaps work-pool introduces

| Gap | Mitigation |
|---|---|
| **Reaper missed dead workers** | `--max-age 30min` default; operator can tighten |
| **Workers crash claiming many items partially** | Per-item idempotency check before RED phase (was the test file already created?) |
| **Dep checker thrash** (blocked/ items checked repeatedly) | Per-worker recent-pass bloom (small in-memory set) |
| **Filesystem rename limits** | None practical; tested at 10k+ files on ext4/apfs/btrfs |
| **Item order semantics lost** | Items sorted by filename — `item-001` picked before `item-002`. If operator wants different order, name accordingly. |
| **Cross-item deps inside a worker's session** | Worker context accumulates across items it picks; no special handling needed if items are independent |
| **Worker shutdown signal** | Workers check for `pool/STOP` file each pick — graceful drain |
| **Pool-empty vs all-claimed-running** | Worker exits if pending is empty; parent waits for all workers to exit before final merge |

## Recommended adoption path

| Phase | Action | Value |
|---|---|---|
| 1 | Document this brainstorm (done) | Decide if it's worth building |
| 2 | Build `_pool_picker.py` + `_pool_worker.py` minimum | ~200 LOC; test with a small 5-item plan |
| 3 | Add `concurrency.mode: "work_pool"` to schema | Lets new plans choose the shape |
| 4 | Render `_pool_init.py` (split master items file) | Operator convenience |
| 5 | Hybrid: pool + chunks in same plan | Real-world fit for the coverage-axes scope |
| 6 | Reaper + status as kaizen-plan subcommands | Operator lifecycle ergonomics |

Build phases 1-3 first as a proof. If it works on a 5-item demo, expand to phase 5 (the realistic 27-item coverage plan).

## Honest assessment vs chunk-based

**Work-pool is the better fit for THIS workload** (300 small-ish coverage ideas, varied difficulty, want to drain them efficiently). Chunk-based is over-engineered for it — we forced 30 ideas into 15 chunks of 2 items each, which is a small enough chunking that the chunk-grouping adds cognitive overhead without dep-grouping value.

**Chunk-based is still better for** design-heavy long-context work where 1 agent owns a coherent multi-day refactor (e.g., axis_runner build — should be one chunk, not 6 items in a pool).

**Hybrid is the realistic answer** for any real plan that has both bulk + design work. The optimal-system synthesis was right that ONE shape was wrong; the answer is letting plans declare both pool items + chunks in the same plan.yaml.

## Recommended next step

Before any code: validate with the user that **work-pool is the right mental model** for the coverage-axes case. If yes:
1. Replace `chunk-sizing.yaml` rubric outputs with worker-sizing (smaller signal set)
2. Build the ~380 LOC pool runtime as Phase 2 of the migration path in `OPTIMAL_SYSTEM.md`
3. Update worked-example to render the coverage-axes plan in hybrid mode (pool + chunks)

This stays YAGNI for the 5-chunk case (don't force pool there) and KISS for the 27-item case (don't force chunks there).
