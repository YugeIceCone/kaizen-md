# Parallel-branches kit — reading order

> **Disciplines:** all rules in [`DISCIPLINES.md`](DISCIPLINES.md) apply. Read it first.

## For an operator new to the kit

Read in this order:

1. **[DISCIPLINES.md](DISCIPLINES.md)** — 10 kit-wide rules (D1 explicit info, D2 floor, D3 line caps, ...). All other docs reference these by ID.
2. **[OPTIMAL_SYSTEM.md](OPTIMAL_SYSTEM.md)** — the synthesized "what the system looks like" doc. Start here for the big picture.
3. **[ON_DISK_LAYOUT.md](ON_DISK_LAYOUT.md)** — Mode A (single file) vs Mode B (split files). Picks Mode B for ≥5 chunks.
4. **[CHUNKING_FLOOR.md](CHUNKING_FLOOR.md)** — the 2-3 items per subagent rule. Why decomposition is bounded.
5. **[CLEVER_LAMA_INTEGRATION.md](CLEVER_LAMA_INTEGRATION.md)** — how we wrap clever-lama's `parallel_subagents` / `chain_subagents` / `agentic_loop` primitives. The runtime layer.
6. **examples/mode-b-split/** — worked example showing the on-disk shape (plan.yaml + chunks/ + merge.yaml + ledger/ + CHECKLIST.md).

## For an operator about to dispatch a plan

7. **[WAVE_DISPATCH_WALKTHROUGH.md](WAVE_DISPATCH_WALKTHROUGH.md)** — concrete walkthrough for waves of 5 agents × N rotations.
8. **[PRE_DISPATCH_AUDIT.md](PRE_DISPATCH_AUDIT.md)** — gaps to check before dispatching. 20 items catalogued by severity.

## For an operator extending the kit

9. **schemas/** — `master-plan.schema.json` + `chunk.schema.json` + 5 fragment schemas + `merge-action.schema.json`
10. **rubrics/chunk-sizing.yaml** — decision rubric (BucketWalker-compatible)
11. **[chunk-plan-template.md](../chunk-plan-template.md)** (parent dir) — the prose template (schema-free version).

## Background brainstorms (kept for context; superseded by current design)

12. **[WORK_POOL_BRAINSTORM.md](WORK_POOL_BRAINSTORM.md)** — earlier atomic-rename pool design. **SUPERSEDED** by `QUEUE_PICKER_BRAINSTORM.md` (parent-as-dispatcher pattern is simpler).
13. **[QUEUE_PICKER_BRAINSTORM.md](QUEUE_PICKER_BRAINSTORM.md)** — current pool-style design (xargs-N mental model). **Now realized via clever-lama's `parallel_subagents`** (see CLEVER_LAMA_INTEGRATION.md).
14. **[SHARED_POOL_BRAINSTORM.md](SHARED_POOL_BRAINSTORM.md)** — coordination pool (heartbeat + messages). **PARTIALLY SUPERSEDED** — clever-lama's `recall_learnings` + skill_stats hooks provide most of what we proposed; Phase A1 heartbeat may still be worth adding.

## Runtime status (clever-lama-mcp side; 2026-05-18)

The runtime modules implementing this kit live in
`~/workspace/mcp-server-stack/clever-lama-mcp/src/parallel_branches/`:

| Phase | Module | Status |
|---|---|---|
| **Phase 1** — load + check | `loader.py` + `checker.py` | ✓ shipped |
| **Phase 1** — dispatch | `dispatcher.py` (`dispatch_wave`) | ✓ shipped |
| **Phase 1** — render | `_plan_render.py` (`render_checklist`) | ✓ shipped |
| **Phase 1** — interwave merge | `merge_handlers.py` ×4 (consolidate_perms / append_progress / render_master_ledger / render_checklist_to_file) | ✓ shipped |
| **Phase 1** — CLI | `_plan_cli.py` (`kaizen-plan` console script) | ✓ shipped |
| **Phase 1** — integration | `test_integration_end_to_end.py` (8-step pipeline against real plan) | ✓ shipped |
| **Phase 2** — final stage | `merge_handlers.py` ×3 (cleanup_fragments / merge_commit / final_verify) | ✓ shipped |
| **Phase 2** — final stage (rest) | wire_mcp_mounts / retrofit / cross_pollinate / dispatch_backlog / cleanup_merged_worktrees | ⏸ deferred (need concrete consumers) |
| **Phase 3** — production wiring | live `parallel_subagents` MCP tool integration | ⏸ deferred |

Total: 7 runtime modules + 56 unit tests + 2 integration tests + 7
merge handlers covering interwave (4) + final (3).

## Document inventory (this folder)

```
parallel-branches/
├── INDEX.md                                    ← this file
├── DISCIPLINES.md                              ← read first
├── OPTIMAL_SYSTEM.md                           ← big picture
├── ON_DISK_LAYOUT.md                           ← Mode A vs Mode B
├── CHUNKING_FLOOR.md                           ← decomposition rules
├── CLEVER_LAMA_INTEGRATION.md                  ← runtime layer (NEW)
├── WAVE_DISPATCH_WALKTHROUGH.md                ← walkthrough
├── PRE_DISPATCH_AUDIT.md                       ← pre-flight gaps
├── README.md                                   ← (legacy intro — superseded by INDEX.md)
├── WORK_POOL_BRAINSTORM.md                     ← superseded
├── QUEUE_PICKER_BRAINSTORM.md                  ← current
├── SHARED_POOL_BRAINSTORM.md                   ← partially superseded
├── schemas/                                    ← 7 JSON Schemas
├── rubrics/chunk-sizing.yaml                   ← decision rubric
└── examples/
    ├── master-plan.example.yaml                ← Mode A worked example
    ├── chunk-ledger.example.jsonl              ← ledger row examples
    └── mode-b-split/                           ← Mode B worked example
        ├── README.md
        ├── plan.yaml
        ├── chunks/chunk-{1,15}.yaml
        ├── merge.yaml
        ├── CHECKLIST.example.md
        └── ledger/MASTER.example.jsonl
```

## Boy-Scout discipline (D10)

When you edit ANY doc in this folder, also fix any discipline violations encountered. Don't leave them for later. If a brainstorm is superseded, mark it inline at the top of the doc (not just here).
