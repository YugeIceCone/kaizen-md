# Queue picker — no racing, items dispensed in order

> User idea sharpened further: "picking without racing issues, there will be a queue waiting in a line (chain), could work like a simple bash process?"

Yes — exactly. The mental model is `xargs -P N`: one source of work, N parallel consumers, ZERO racing because the source is sequential and the parallel work happens AFTER the pick. This is much cleaner than the atomic-rename pool from the prior brainstorm.

## The bash mental model (the simplest possible shape)

```bash
ls pool/pending/*.yaml | sort | xargs -P 5 -n 1 ./worker.sh
```

That's it. Decomposed:
- `ls pool/pending/*.yaml` — source: sorted list of pending items
- `sort` — deterministic order
- `xargs -P 5` — keep 5 workers busy in parallel
- `-n 1` — each worker gets ONE item at a time via argv
- `./worker.sh` — each worker runs this with its assigned item

**Why no racing:** xargs is a single dispatcher. It reads stdin one line at a time and feeds it to whichever child process is ready. Two workers never see the same item because xargs hands each item to exactly one child.

**Why ordering is preserved:** `sort` + xargs's FIFO dispatch order = items processed in lexicographic order. (Within parallelism, completion order is unpredictable, but pick order is deterministic.)

## Translation to the CC Agent ecosystem

The CC Agent tool is one-shot synchronous — can't directly fit inside `xargs`. But the SAME shape works with the parent as dispatcher:

```python
# Parent loop (in the CC orchestrator)
pool = sorted(Path("pool/pending").glob("*.yaml"))
POOL_SIZE = 5  # max parallel agents

i = 0
while i < len(pool):
    batch = pool[i:i+POOL_SIZE]
    # Dispatch this batch as N parallel Agent() calls; each gets ONE assigned item
    results = [
        Agent(description=f"Item {item.name}", subagent_type="kaizen-implementer",
              isolation="worktree", prompt=render_item_prompt(item))
        for item in batch
    ]
    # Wait for all in the batch (Agent tool returns when each finishes)
    for item, result in zip(batch, results):
        if result.success:
            os.rename(f"pool/pending/{item.name}", f"pool/done/{item.name}")
        else:
            os.rename(f"pool/pending/{item.name}", f"pool/failed/{item.name}")
    i += POOL_SIZE
```

**Key shift from prior work-pool brainstorm:** parent dispatches a specific item to a specific Agent. **Workers don't pick — they're handed work.** Racing impossible by construction.

## Why this is cleaner than the atomic-rename pool

| Concern | Atomic-rename pool (prior brainstorm) | Queue picker (this) |
|---|---|---|
| Racing on pick | Filesystem mediates (1 winner per rename) | None — parent dispenses, single source of truth |
| Worker idempotency | Required (worker dies mid-claim → stuck item) | Not required — parent knows assignments |
| Reaper for stuck claims | Mandatory | Not needed |
| Worker prompt complexity | "look for next item, try to claim, work it" | "do item X" |
| Failure semantics | Worker moves to failed/ | Parent moves to failed/ based on Agent() result |
| Resumability | `ls pool/pending/` shows what's left | Same — `ls` is universal |
| Mental model | "5 racing workers" | "5 workers waiting in a chain" |
| Implementation LOC | ~380 (picker + worker + reaper + idempotency) | ~120 (just parent dispatch loop + render_item_prompt) |

**~70% less runtime code** for the same effective behavior, because the parent absorbs all coordination.

## Why "chain" / "waiting in line" is the right framing

The user said "queue waiting in a line (chain)". That maps to:

```
pending/  ──→  [pool[0], pool[1], ..., pool[N]]   (sorted; the line)
                  │
                  ▼
              dispatcher (parent)
                  │
                  ▼ (one item at a time)
              ┌───┴───┬───────┬───────┬───────┐
              │       │       │       │       │
           worker  worker  worker  worker  worker
           slot-1  slot-2  slot-3  slot-4  slot-5
              │       │       │       │       │
              └───┬───┴───────┴───────┴───────┘
                  ▼
              done/  ←  parent moves item on success
              failed/ ←  parent moves item on failure
```

Items wait IN LINE in `pending/`. The dispatcher pulls one at a time. Workers in slots take whatever the dispatcher gives them. **No two workers ever look at the same item.**

This is the classic producer-consumer / bounded-parallelism pattern. Implemented in 100+ languages. KISS to the bone.

## Implementation: simplest possible orchestrator

```python
# orchestrator.py — runs in the parent CC context
import os
from pathlib import Path

POOL = Path("pool")
POOL_SIZE = 5

def dispatch_pool():
    pending = sorted(POOL.glob("pending/*.yaml"))
    while pending:
        # Take next batch
        batch, pending = pending[:POOL_SIZE], pending[POOL_SIZE:]

        # Dispatch all in parallel via Agent tool (single message, N calls)
        results = parallel_agent_dispatch(batch)

        # Move based on outcome — parent is single writer to pool/
        for item, success in zip(batch, results):
            target = "done" if success else "failed"
            os.rename(item, POOL / target / item.name)

        # Optional: refresh CHECKLIST.md here
        # Optional: interwave merge here if natural wave boundary

    return {"done": ls("done"), "failed": ls("failed")}
```

**~30 LOC of orchestration logic.** Plus `render_item_prompt(item)` (~50 LOC — generates the Agent prompt from the item YAML) and `parallel_agent_dispatch(batch)` (~20 LOC — wraps the parent's actual Agent tool calls into a single message).

**Total: ~100 LOC.** Much less than either prior brainstorm.

## What about deps?

If item-007 depends on item-003 being done, the parent skips item-007 until item-003 is in `done/`:

```python
def deps_satisfied(item: Path, done_set: set[str]) -> bool:
    item_data = yaml.safe_load(item.read_text())
    return all(dep in done_set for dep in item_data.get("deps", []))

# In the loop:
done_set = {p.name for p in (POOL / "done").iterdir()}
batch = []
for item in pending:
    if deps_satisfied(item, done_set):
        batch.append(item)
        if len(batch) >= POOL_SIZE:
            break
    # else: skip; will be revisited next loop iteration once dep clears
```

Simple. No `blocked/` dir needed — items just stay in `pending/` until their deps are done. Each iteration of the while-loop re-evaluates.

If the parent skips ALL remaining items (every one has unmet deps), we have a circular dep or a real stall. Parent detects (no progress in N iterations) → abort with clear error.

## What about long-running workers (warm context)?

The atomic-rename brainstorm pitched: "a worker picks several items in a row, amortizing skill-load cost across items."

In the queue-picker model, that's also possible — but instead of workers self-picking, the parent dispatches BATCHES of items to a single agent:

```python
# Alternative: instead of 1 item per agent, dispatch N items to each agent
# (when items are tiny and skill-load dominates per-agent cost)
batch_of_batches = [pending[i:i+ITEMS_PER_AGENT] for i in range(0, len(pending), ITEMS_PER_AGENT)]
for batch_of_items in batch_of_batches:
    # Each agent gets MULTIPLE items at once; runs them sequentially in its session
    # Skill loads happen once per agent, not once per item
    Agent(prompt=render_batch_prompt(batch_of_items))
```

This is essentially "chunks" again — but now the parent BUILDS chunks dynamically from the pool rather than the operator hand-authoring them. Same token savings as the atomic-rename pool's "warm worker" benefit, but with parent-controlled batching.

**Recommended: `ITEMS_PER_AGENT: 3`** — gives 3× skill-load amortization without burning agent context on 10+ items in one shot.

## Bash version for non-CC workflows

If the workers were ordinary Python scripts (not CC Agents), the entire orchestrator is one line:

```bash
ls pool/pending/*.yaml | sort | xargs -P 5 -n 1 -I {} python3 worker.py {}
```

`worker.py` reads its assigned item, does the work, exits with 0 (success) or 1 (failure). Parent script post-processes:

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p pool/{done,failed}

# Pipe pending items into xargs; xargs runs worker.py for each in parallel
ls pool/pending/*.yaml | sort | xargs -P 5 -n 1 -I {} bash -c '
    if python3 worker.py "$1"; then
        mv "$1" pool/done/
    else
        mv "$1" pool/failed/
    fi
' _ {}

echo "done: $(ls pool/done/ | wc -l)"
echo "failed: $(ls pool/failed/ | wc -l)"
```

**~15 lines of bash for a parallel work-pool with no racing.** Works on macOS, Linux, anything POSIX.

## Comparison — all three coordination shapes

| Mechanism | Racing | Worker complexity | Parent role | LOC | Best for |
|---|---|---|---|---|---|
| **Atomic-rename pool** (prior brainstorm) | Yes — filesystem mediates | High (claim/retry/idempotency/reaper) | Minimal (spawn N workers, walk away) | ~380 | Long-running daemon-style workers, fault-tolerance |
| **Queue picker** (this) | None — parent dispenses | Low (just "do item X") | Coordinator (batches + waits + moves) | ~100 | CC Agent ecosystem, single orchestration session |
| **Chunk-based wave** (current kit) | None — chunks pre-assigned | Low (handed your chunk) | Wave coordinator (dispatch + wait + merge) | ~980 | Few coherent chunks, design-heavy work |

## What this changes vs the current kit

| Kit feature | With queue picker |
|---|---|
| `chunks/*.yaml` | Replaced by `pool/pending/*.yaml` (smaller, leaf-level items) |
| `chunk-sizing` rubric | Replaced by `worker-sizing` rubric (just pool_size) |
| `wave_size` + waves | Becomes batch_size in the parent loop — no separate concept needed |
| `interwave_merge` | Becomes "every N batches, run partial merge" — same mechanic, different trigger |
| `chunk.schema.json` | Replaced by `item.schema.json` (simpler — one TDD unit) |
| `.chunks/N/` fragments | Becomes `.chunks/item-NNN/` fragments — same shape, finer granularity |
| Worktrees | One per worker SLOT (not per item) — slot reused across items |

The kit's other elements (Mode B split files, ledger, checklist, merge stages, isolation contract) all apply unchanged.

## The full proposed shape

```
docs/superpowers/plans/<plan-name>/
├── plan.yaml                        ← concurrency: { mode: "queue_picker", pool_size: 5, items_per_agent: 3 }
├── pool/
│   ├── pending/
│   │   ├── item-001.yaml
│   │   └── ...
│   ├── done/                        ← parent moves items here on success
│   └── failed/                      ← parent moves items here on failure
├── chunks/                          ← optional — for design-heavy non-pool work
│   └── chunk-axis-runner.yaml
├── merge.yaml                       ← same stages: interwave + final
├── ledger/
│   ├── MASTER.jsonl
│   └── SHARED/                      ← optional coordination pool
└── CHECKLIST.md                     ← shows pool/ state directly: ls counts per dir
```

Operator runbook becomes:

```bash
kaizen-plan init --pool --items-from-brainstorm <jsonl> --pool-size 5 --out <plan-dir>
kaizen-plan check
kaizen-plan dispatch --plan plan.yaml  # parent runs the batch loop until pool empty
kaizen-plan merge --stage final
kaizen-plan status                     # ls pool/{done,failed,pending}/ rolled up
```

**5 commands** (down from 6 in the optimal-system; no per-wave dispatch + merge cycle because the parent loop handles batching internally).

## Recommendation

**Adopt the queue-picker shape as the default for items-mode plans.** It:
- Eliminates racing entirely (parent is single writer to pool/)
- Cuts runtime LOC by ~70% vs atomic-rename pool
- Maps cleanly to both `xargs -P N` (bash) and parent-driven Agent batching (CC)
- Keeps the same on-disk shape (pending/done/failed)
- Composes with the existing kit (Mode B + fragments + ledger + merge stages all unchanged)

**Keep chunks/** for the few design-heavy items that genuinely need long-running coherent context. Hybrid (pool items + chunks) remains the realistic answer for any plan with mixed item shapes.

## What changes in `OPTIMAL_SYSTEM.md`

If we ratify this:
- Replace "Wave mode default (5/wave)" with "Queue-picker default (pool_size: 5)"
- Replace `_pool_picker.py` (~80 LOC) + `_pool_worker.py` (~120 LOC) + `_pool_reap.py` (~60 LOC) with `_queue_picker.py` (~100 LOC total)
- Drop `_pool_init.py` requirement (just `pool/pending/` directory of files; no special init needed beyond writing the files)
- Phase 2 LOC drops from ~430 to ~250

## Honest assessment

The atomic-rename worker-pool brainstorm was clever but over-engineered for our case. The queue picker is the **simplest thing that could possibly work**, maps to a one-liner `xargs -P N` in bash, and eliminates entire categories of failure (no idempotency, no reaper, no worker registration).

**The right mental model is `xargs -P 5`**, with the parent CC orchestrator playing the role of xargs for Agent calls. Workers wait their turn in line; the dispatcher hands them items; no two workers ever look at the same thing.

## Recommended next move

Replace `WORK_POOL_BRAINSTORM.md`'s atomic-rename mechanic with this queue-picker mechanic. Same on-disk shape, simpler runtime, no racing. Sketch a ~100-LOC orchestrator skeleton (Python) as proof; test it on 5 items before scaling.
