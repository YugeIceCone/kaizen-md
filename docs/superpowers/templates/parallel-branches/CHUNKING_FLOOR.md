# Chunking floor — the discipline

> User principle: "you don't arbitrarily break something down that you can do yourself, lets set a floor that fits for 1 subagent"

## The rule

**Decompose only when forced.** A "chunk" is the smallest unit of work that:
1. Saturates a subagent's available budget (≥ ~70% of the 35k cap), AND
2. Cannot be done by the current orchestrator without delegation

Going smaller than the floor pays full setup cost for half the work — a DRY/KISS violation. Going larger overruns the budget — needs split.

## Two-tier floor

**Tier 0 — parent does it (no subagent dispatch at all):**
- Work fits in 1-3 TDD cycles ≤ ~25k tokens in the parent context
- Parent has the required skills + exemplars already loaded
- No need to isolate via worktree (single-session work)

→ **Just do it.** No plan.yaml, no chunks, no fragments. Direct work in the parent.

**Tier 1 — single subagent (1 chunk, no decomposition):**
- Work needs isolated context (worktree, fresh skill loads, clean exemplar reads)
- Fits within one subagent's 20-35k budget
- Floor: ≥ 2 substantive items per subagent (else parent should do it directly)

→ **One Agent() call.** Single chunk file; no pool, no waves, no merge ritual.

**Tier 2 — chunked subagents (decomposition justified):**
- More work than one subagent can hold
- Decompose into chunks where **each chunk = 2-3 items per subagent**
- Below 2 items/subagent: wasteful (setup cost > work cost)

→ Chunk count = `ceil(items / 3)`. Use the chunk-based or queue-picker shape.

**Tier 3 — work pool (many items, varied difficulty):**
- ≥30 items, varied per-item cost, want load balancing
- Use queue-picker (parent as xargs) with N worker slots
- Each worker handles 2-3 items per session before exit

→ Pool with worker batches sized at the floor.

## Token math — why the floor is 2-3 items per subagent

From this session's empirical data + per-axis costing:

| Component | Cost                                       |
|-----------|--------------------------------------------|
| Subagent setup (system prompt + 2 skill loads + 1-2 exemplar reads) | ~12-18k |
| Per-item work (test + RED + script + bin + perm + GREEN + commit + gate echo) | ~6-10k |
| Per-iteration context growth | ~1-2k |
| Retry / gate-warn buffer (15%) | ~3-5k |
| **Subagent cap** | **20-40k** |

Items per subagent (within 35k effective cap):

| Items | Total cost | Verdict |
|-------|------------|---------|
| 1     | ~25k       | **Under floor** — pay setup once for one item is wasteful |
| 2     | ~33k       | **AT FLOOR** — comfortable; this is the minimum |
| 3     | ~42k       | **OVER CAP** for substantive items; OK for trivial grep/regex axes |

**Floor = 2 substantive items per subagent.** 3 only if items are tiny.

## Why the parent should do small work directly

A trivial axis (~5-7k of focused work) in PARENT context:
- 0 setup cost (parent already has skills loaded)
- ~5-7k for the work
- Total: ~5-7k

Same axis dispatched to a subagent:
- 15k setup
- 7k work
- 22k total

**3-4× cost amplification for delegating something the parent could do.** Only delegate when:
- Work needs isolated worktree (the contract was about isolation)
- Parent context is near cap (delegation off-loads pressure)
- Work is design-heavy and benefits from fresh subagent focus
- Parallelism is required (5 things at once)

If none of those apply → parent does it.

## Decision tree

```
                    "I have N items to work"
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
           N ≤ 3?        4 ≤ N ≤ 6?         N ≥ 7?
              │               │               │
              ▼               ▼               ▼
       Tier 0:           Tier 1:          Tier 2 or 3:
       Parent does it    One subagent     Decompose
                                            │
                                            ▼
                           ┌────────────────┴────────────────┐
                           ▼                                  ▼
                      N ≤ 30?                            N > 30?
                           │                                  │
                           ▼                                  ▼
                  Chunked (2-3 items/chunk)          Queue picker (pool)
                  Chunk count = ceil(N/3)            Pool size = 5 workers
                                                     Items per worker = 2-3
```

## Apply to the 27-item coverage-axes scope

| Decomposition | Chunks/workers | Items/unit | Tokens/unit | Verdict |
|---|---|---|---|---|
| 27-chunks-of-1 | 27 | 1 | 25k | ❌ Way under floor; 50% waste |
| 15-chunks-of-2 (current plan) | 15 | 2 | 33k | ✓ AT FLOOR |
| **9-chunks-of-3** | **9** | **3** | **38-42k** | ✓ **At floor (slight overage; OK for mostly grep)** |
| 5-chunks-of-5 | 5 | 5 | 55k+ | ❌ Over cap; would need handoffs |

The **15-chunk plan is at the floor.** Could compress to **9 chunks of 3** if the items are mostly trivial (grep/regex axes). Cannot compress further without violating the cap.

For the 30 axes already shipped this session: PARENT did them all (~17k/axis in parent context). That worked because the parent had shared skills loaded. A fresh subagent doing 30 axes would need ~10 chunks at the floor.

## Rubric update — floor-aware sizing

The current `chunk-sizing.yaml` returns buckets like `GRID_5` / `GRID_15`. Floor-aware version:

```yaml
# rubrics/chunk-sizing.yaml — floor-aware update
version: 2

rules:
  # 1. PARENT_DOES_IT — too small to delegate
  - bucket: PARENT_DOES_IT
    require_all:
      - {signal: total_items,    op: "<=", value: 3}
      - {signal: per_axis_cost_k, op: "<=", value: 8}
    # → no plan.yaml, no subagent dispatch; just work directly

  # 2. ONE_SUBAGENT — single subagent, no decomposition
  - bucket: ONE_SUBAGENT
    require_all:
      - {signal: total_items, op: ">=", value: 4}
      - {signal: total_items, op: "<=", value: 6}
    # → 1 chunk; ceil(items/3) = 2 chunks if items=6 actually,
    #   but for borderline cases pack into one and accept ~40k

  # 3. CHUNKED — decompose into floor-sized chunks
  - bucket: CHUNKED
    require_all:
      - {signal: total_items, op: ">=", value: 7}
      - {signal: total_items, op: "<=", value: 30}
    # → chunk_count = ceil(total_items / floor_items_per_chunk)
    # → floor_items_per_chunk = 3 (or 2 for design-heavy items)

  # 4. POOL — many varied items
  - bucket: POOL
    require_all:
      - {signal: total_items, op: ">", value: 30}
    # → queue-picker mode; pool_size=5 workers; items_per_worker=3

confidence_threshold: 0.85
fallback: NEEDS_AGENT
```

Then the operator (or `kaizen-plan size` CLI) computes:

```python
chunk_count = math.ceil(total_items / floor_items_per_chunk)
# floor_items_per_chunk = 3 for grep/regex axes; 2 for substantive
```

## The discipline in one sentence

**Decompose at the floor (2-3 items per subagent), not below it; if the whole plan fits in one subagent or parent, don't decompose at all.**

## Tradeoffs of getting the floor wrong

| Mistake | Cost |
|---|---|
| Floor too low (e.g. 1 item/subagent) | Setup overhead × N — easily 50-100% token waste |
| Floor too high (e.g. 5+ items/subagent) | Cap breaches → mid-flight handoffs → state-management complexity |
| Decompose when parent could do it | 3-4× cost amplification + loses shared-context advantage |
| Don't decompose when work exceeds parent cap | Parent runs out of context mid-work; loses prior commits in context squeeze |

The floor is the sweet spot — large enough that setup amortizes, small enough that the cap holds with margin.

## Applies to all three coordination shapes

Floor is **shape-invariant** — applies to chunk-based, queue-picker, and worker-pool equally:

- **Chunk-based:** each chunk owns 2-3 items
- **Queue-picker:** parent dispatches batches of 2-3 items per agent
- **Worker pool:** each worker session processes 2-3 items before exit

The shape determines HOW the items are routed; the floor determines HOW MANY per agent.

## Updates downstream of this discipline

| Doc | What to change |
|---|---|
| `OPTIMAL_SYSTEM.md` | "Default budget 30k" → add: "Default items_per_subagent: 2-3 (floor)" |
| `chunk-sizing.yaml` | Add `PARENT_DOES_IT` + `ONE_SUBAGENT` buckets; floor-aware GRID sizing |
| `QUEUE_PICKER_BRAINSTORM.md` | `items_per_agent: 3` default (instead of 1) |
| Plan templates | Drop sub-2-item chunks; warn at validation if any chunk has < 2 items |
| `_plan_check.py` | Add floor check: warn on chunks with < 2 items unless design-heavy flag set |

## Honest application to this session's work

Looking back at the 15-chunk dynamic-chunks plan: 13 of 15 chunks have 2 items each ✓ (at floor); chunk 3 has 1 item (axis_runner #161) — but the chunk is design-heavy (~120 LOC equivalent design work) so it stays at 1-item legitimately; chunk 15 is cross-repo (1 logical unit) so also legit.

**The 15-chunk plan respects the floor.** A 30-chunk-of-1 plan would not have.

## TL;DR

- Floor = **2-3 items per subagent**
- Below floor = wasteful (don't do it)
- If total plan ≤ 3 items → parent does it (no subagent at all)
- 4-6 items → one subagent
- 7-30 items → chunks of 3 items each = `ceil(N/3)` chunks
- 30+ items → queue-picker pool with 5 workers × 2-3 items per worker session

**Decomposition is justified only when forced** — by the per-agent cap, by isolation needs, by parallelism requirements. Otherwise: just do the work.
