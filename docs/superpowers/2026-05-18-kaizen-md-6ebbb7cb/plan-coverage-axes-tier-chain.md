# Coverage-axes — tier-as-chain decomposition (alternative to dynamic chunks)

- **Date:** 2026-05-18
- **Scope:** complementary to `2026-05-18-coverage-axes-dynamic-chunks.md`. Same total deliverables, different decomposition shape: **each tier owns one agent**, agents are **chained** (T1 → T2 → T3 → T4 → X → MERGE), each link runs as a `/kaizen:loop` over its tier's pending items.
- **When to use this shape vs. the 15-chunk grid:**

| Decomposition | Pros | Cons | Use when |
|---|---|---|---|
| **15-chunk grid** (dynamic-chunks.md) | maximum parallelism; even chunk sizes; predictable budgets | many parallel agents; complex orchestration | many agent slots available; want fastest wall-clock |
| **Tier-chain** (this file) | clean mental model (1 agent = 1 tier); natural priority order (T1 ships first); each agent specializes in tier-shaped work | sequential — slower wall-clock; T3 + T4 need mid-flight handoff to stay in budget | few agent slots; want priority-ordered shipping; debuggability matters more than speed |

Both decompositions share the same isolation contract (`.chunks/N/` fragments, no canonical-file writes) and the same MERGE step at the end. Choose one — don't mix.

## Chain topology

```
   T1: tier-1 (5 items)          ─┐
       ↓                           │
   T2: tier-2 (5 items)            │  Each link is ONE agent
       ↓                           │  running /kaizen:loop over
   T3: tier-3 (13 items)           │  its tier's pending items.
       ↓                           │
   T4: tier-4 (deferred)           │  Auto-handoff to next slot at
       ↓                           │  ~30k context (avoid /compact).
   X:  cross-repo (semantic-search)│
       ↓                           │
   M:  MERGE (parent orchestrator)─┘
```

**Why a chain (not parallel):** later tiers can consume infrastructure earlier tiers built. T1 ships `axis_runner` (#161); T2/T3 can then declare new axes as YAML instead of standalone Python (smaller per-axis cost). This compounds across the chain — earlier tier work pays back in later tiers.

## Token-cost model (per-tier-agent, /loop shape)

`/kaizen:loop` agents have **lighter per-iteration cost** than fresh subagents (no skill re-loads per iteration, shared exemplar memory across iterations), but **growing context** as iterations accumulate.

| Component                       | Range       | Notes                                                  |
|---------------------------------|-------------|--------------------------------------------------------|
| Loop startup                    | ~8-12k      | tier-ledger read + skill loads (one-time per agent)    |
| Per-iteration cost              | ~3-5k       | test + impl + bin + perm + commit + ledger tick        |
| Context growth per iter         | ~2k         | accumulates until auto-handoff fires                   |
| Auto-handoff threshold          | 30k context | spawns sibling continuation agent (`kaizen:auto-handoff`) |

**Tier sizing:**

| Tier | Items | Iterations | Single-agent budget | Needs handoff? |
|------|-------|------------|---------------------|----------------|
| T1   | 7 (5 tier-1 + 2 axis_runner halves) | 7 | ~10k + 7×4k = ~38k | borderline — one handoff at iter ~5 |
| T2   | 5     | 5          | ~10k + 5×4k = ~30k  | no                                  |
| T3   | 13    | 13         | ~10k + 13×4k = ~62k | yes — handoff at iter ~6 (then iter 7-13 in 2nd slot) |
| T4   | 250   | 250        | unbounded           | **out of scope** — file separate plan |
| X    | 5     | 5          | ~10k + 5×4k = ~30k  | no                                  |
| M    | merge | 1 pass     | ~22k                | no                                  |

**Peak per-agent budget: ~32-38k** (T3 first half before handoff). Well within the 20-40k cap when handoffs fire.

## Chain stages

### Stage T1 — tier-1 chain link

| field        | value                                                                                                          |
|--------------|----------------------------------------------------------------------------------------------------------------|
| **Purpose**  | Ship all 5 remaining tier-1 items + axis_runner (#161 split into core+mcp halves = 2 logical sub-iters)        |
| **Items**    | #57 lifecycle-audit, #92 trace-bloat-join, #151 append-to-audit, #153 stream-join, #161-core, #161-mcp         |
| **Project**  | kaizen-md                                                                                                      |
| **Worktree** | `chain-t1`                                                                                                     |
| **Subagent** | `kaizen-implementer` running `/kaizen:loop --tier 1`                                                           |
| **Budget**   | ~38k (auto-handoff if exceeded)                                                                                |
| **Ledger**   | `.chunks/t1/ledger.jsonl` (one row per item with `status: pending|in_progress|done`)                           |

**Loop body (per iter):** read tier-1 ledger → pick next `pending` item → TDD it → commit → flip status to `done` → emit fragment writes if last item.

**Done when:** all tier-1 items `done` in ledger; `.chunks/t1/{perms.json, progress.md, mcp-mounts.txt}` fragments present.

**Dispatch:**
```python
Agent(description="Tier 1 chain link",
      subagent_type="kaizen-implementer", isolation="worktree",
      prompt="""Run /kaizen:loop over the tier-1 brainstorm queue.
WORKING DIR: /home/cherry86/workspace/kaizen-md
LEDGER: .chunks/t1/ledger.jsonl (pre-seeded with 6 items: #57, #92, #151, #153, #161-core, #161-mcp)
SKILLS: kaizen:tdd, kaizen:plugin-development, kaizen:loop
LOOP: drain the ledger end-to-end; one item per iter (RED→GREEN→commit→tick).
ISOLATION: NEVER write plugin.json / progress.md / backlog.json / gateway.py — fragments only.
AUTO-HANDOFF: at 30k context, spawn sibling agent with same ledger.
BUDGET: ~38k. DONE WHEN: ledger empty + fragments written.""")
```

### Stage T2 — tier-2 chain link (waits for T1 complete)

| Items: #10 fn-name, #18 validator-wiring, #23 mock-real, #24 mutation-gate, #47 iron-law-per-feature |
| Worktree: `chain-t2` · Budget: ~30k · Ledger: `.chunks/t2/ledger.jsonl` |

**Why T2 after T1:** T2's `#47 iron-law-per-feature` benefits from `axis_runner` (T1 ships) — can declare as YAML axis instead of standalone Python, saving ~3k/item.

### Stage T3 — tier-3 chain link (waits for T2 complete)

| Items (13): #1 comment, #19 yaml-strict, #21 skipped-test, #26 mcp-latency, #28 cold-start, #29 cold-start-map, #33 dxm-registry, #39 skill-sections, #40 skill-refs, #41 slash-docstring, #42 changelog, #48 cc-drift, #49 archlog-align |
| Worktree: `chain-t3` · Budget: ~62k (handoff at ~iter 6 → 2nd slot ~32k) |

**Why T3 needs handoff:** 13 items × 4k context-growth/iter = 52k accumulated; even with /loop's lighter cost, exceeds 40k. The kaizen:auto-handoff hook (already shipped at 85% threshold from earlier work) fires automatically, persists ledger + state, spawns sibling agent in a new slot. Sibling reads `.chunks/t3/ledger.jsonl` (already partly ticked) and continues.

**Why T3 after T2:** by this point, axis_runner + 30+ existing axes give rich exemplar surface. T3 items (mostly docs/lint shapes) often retrofit cleanly to YAML.

### Stage T4 — DEFERRED (250 tier-4 ideas)

Not in this chain. File a separate plan when explicitly requested. The 5 priority tiers (1-2-3 of brainstorm + new NEW + axis_runner + cross-repo) ship complete via T1+T2+T3+X. Tier 4 is intentionally a separate effort.

### Stage X — cross-repo (waits for T3 complete)

| Project: semantic-search · Items: wire 3 gates + run 30+chunks-shipped axes against semantic-search + file findings backlog |
| Worktree: n/a (different repo) · Budget: ~30k (more axes to run now than in 5-chunk version) |

**Why X after T3:** by this point ALL kaizen-md axes exist (30 prior + 23 new + axis_runner). X gets the full benefit when auditing semantic-search.

### Stage M — MERGE (parent orchestrator, waits for X complete)

Same as `2026-05-18-coverage-axes-dynamic-chunks.md::Merge step`. Single-writer consolidation of `.chunks/{t1,t2,t3}/` fragments into canonical files + retrofit + cross-pollination. Budget: ~22k.

## Isolation contract (applies to every link)

**Owns (exclusive write):**
- `.chunks/<tier>/` (fragment dir + ledger)
- `skills/workflow/scripts/<tier-specific-axes>.py` (different names per tier — no overlap)
- `tests/test_<tier-axis>.py`
- `bin/kaizen-<tier-axis>` (NEW symlinks only)

**NEVER writes:**
- `plugin.json`, `progress.md`, `backlog.json`, `gateway.py::SUBSERVERS` (all MERGE-step responsibility)
- Any prior tier's ledger or fragment dir
- Files outside its tier's item list

**Fragment writes happen continuously** (per iter ledger-tick), not only at chain-link close-out. That way auto-handoff carries no lossy state across agent slot boundaries.

## Dispatch — operator runbook

**Sequential** (the chain — recommended):
```python
# Wait for each to complete before launching the next
Agent(stage-t1) ; wait ; Agent(stage-t2) ; wait ; Agent(stage-t3) ; wait ; Agent(stage-x) ; wait ; Agent(stage-merge)
```

**Parent-driven adaptive** (auto-launches next link on prior completion):
- Use `kaizen:auto-handoff` hook + the loop's `--on-done dispatch-next` flag (configure via `kaizen-workflow set --chain T1,T2,T3,X,M`)

**Hybrid** (T1+T2 sequential, T3 in 2 sibling slots, X parallel with M-staging):
- T1 → T2 → T3a + T3b (after T3 handoff, the 2nd slot picks up the back half) → X → M
- This gets ~30% wall-clock savings while keeping the dependency chain intact

## Plan-level done when

- [ ] All 4 stage ledgers (`t1, t2, t3, x`) empty
- [ ] All 3 tier fragments + cross-repo deliverables in master
- [ ] MERGE step's 9 actions complete
- [ ] Coverage rollup: tier-1 21/21, tier-2 12/12, tier-3 17/17 — all priority tiers complete
- [ ] Final smoke: full suite + test-pipeline.sh green

## Comparison — chain-of-tiers vs 15-chunk grid

| Property               | Chain-of-tiers (this plan)             | 15-chunk grid (sibling plan)                  |
|------------------------|----------------------------------------|-----------------------------------------------|
| Total deliverables     | 23 + 3 NEW + axis-runner + cross-repo  | same                                          |
| Number of agent slots  | 4 (+ MERGE) sequential                 | 15 parallel + MERGE                           |
| Wall-clock             | ~4-6× longer (sequential)              | ~1× (max parallelism)                         |
| Peak per-agent budget  | ~38k (with auto-handoff for T3)        | ~38k (max chunk size)                         |
| Total token budget     | ~180k (less repeated setup)            | ~475k (15× setup overhead)                    |
| Compounding wins       | YES — later tiers reuse axis_runner   | NO — chunks 1-14 all build standalone         |
| Debugability           | High — one failure ≠ chain stall      | High — chunks are dep-free, retry any chunk   |
| Mental model           | Priority-ordered (T1 ships first)      | Domain-clustered (axes-by-shape)              |

**Token economy:** the chain saves ~295k tokens (~60% reduction) by avoiding per-chunk setup overhead. The trade is wall-clock — chains run sequentially. Pick the shape based on which resource is scarcer (token budget vs operator time).
