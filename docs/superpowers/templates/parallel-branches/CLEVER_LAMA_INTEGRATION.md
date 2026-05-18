# Clever-lama integration — runtime primitives

> **Disciplines:** all rules in [`DISCIPLINES.md`](DISCIPLINES.md) apply. See D8 (KISS over capability) + D9 (YAGNI over speculation) especially — this doc cuts ~50% of planned runtime LOC by reusing already-shipped primitives.

The clever-lama-mcp server (`~/workspace/mcp-server-stack/clever-lama-mcp/`, 46 MCP tools) ships **runtime primitives that subsume most of what `OPTIMAL_SYSTEM.md` proposed building from scratch**. This doc maps each kit phase to its clever-lama tool, what the wrapper code needs to do, and what falls back to bespoke.

## Tool map (kit phase → clever-lama tool)

| Kit phase                    | Original plan (LOC est) | Now uses (LOC actual)                                       |
|------------------------------|-------------------------|--------------------------------------------------------------|
| Plan loader                  | `_plan_loader.py` ~80  | `_plan_loader.py` ~80 (glue only — Mode B globs)            |
| Pre-flight check             | `_plan_check.py` ~150  | `_plan_check.py` ~150 + reuses `mcp__clever-lama__parallel_grep` for cross-chunk path scanning |
| **Per-wave dispatch**        | `_plan_dispatch.py` ~200 | **~30 LOC wrapper** around `mcp__clever-lama__parallel_subagents` |
| **Tier-chain dispatch**      | (not planned — required NEW LOC) | **`mcp__clever-lama__chain_subagents`** — already exists! |
| **Queue-picker workers**     | `_pool_picker.py` + `_pool_worker.py` + `_pool_reap.py` ~260 | **`mcp__clever-lama__agentic_loop`** for self-driven workers; OR `mcp__clever-lama__parallel_bash` for `xargs -P N` shape |
| Merge handlers               | `_merge_handlers.py` ~300 | `_merge_handlers.py` ~300 (no clever-lama equivalent — bespoke) |
| Checklist renderer           | `_plan_render.py` ~150 | `_plan_render.py` ~150 (bespoke) + reuses `mcp__clever-lama__recall_learnings` for cross-plan history |
| Verify / failure-detection   | (not planned)            | **`mcp__clever-lama__verify_with_uncertainty`** — Algorithm 1 self-consistency for "did this chunk really succeed?" |
| Branch scoring               | (not planned)            | **`mcp__clever-lama__score_branches`** — score competing chunk variants |
| Cross-plan learning          | (not planned)            | **`mcp__clever-lama__recall_semantic`** — semantic search across past plan runs |
| Worktree orchestration       | ~80 LOC bespoke         | ~80 LOC bespoke (no equivalent) — git is git              |
| CLI                          | `_plan_cli.py` ~100    | `_plan_cli.py` ~100                                          |

**Original LOC: ~980. With clever-lama primitives: ~660. Net savings: ~320 LOC** (~33%).

## Per-primitive deep dive

### `mcp__clever-lama__parallel_subagents` — wave dispatcher

What it does: spawns N subagents in parallel, each with its own prompt + isolated context. Returns when all N complete (or one fails per failure_policy).

How we use it (Phase 1 wave dispatch):

```python
# _plan_dispatch.py — pseudo-code (real impl ~30 LOC)
def dispatch_wave(chunks_in_wave: list[dict]) -> list[dict]:
    """Render N chunk prompts; call parallel_subagents; return results."""
    prompts = [render_prompt(c) for c in chunks_in_wave]  # _plan_render handles
    # Invoke via MCP tool (parent has clever-lama mounted)
    return mcp__clever_lama__parallel_subagents(
        tasks=[{"id": c["id"], "prompt": p} for c, p in zip(chunks_in_wave, prompts)],
        timeout_per_agent_seconds=600,
    )
```

Replaces ~200 LOC of bespoke Agent-tool batching + wait-barrier logic. We get retry semantics, parallel-fanout, and failure isolation for free.

### `mcp__clever-lama__chain_subagents` — tier-chain mode

What it does: runs subagents sequentially; each receives the prior's output. Perfect for tier-chain (T1 ships axis_runner → T2 uses it → T3 uses both).

How we use it (TIER_CHAIN bucket):

```python
def dispatch_tier_chain(tier_agents: list[dict]) -> list[dict]:
    return mcp__clever_lama__chain_subagents(
        tasks=[{"id": a["id"], "prompt": render_prompt(a)} for a in tier_agents],
    )
```

Replaces the entire tier-chain bespoke runtime. Was going to be ~150 LOC; now ~30 LOC of glue.

### `mcp__clever-lama__agentic_loop` — queue-picker worker

What it does: agent autonomously loops (Decide → Dispatch → Observe → loop) until a stop condition. Each iteration picks next work, executes, ticks state.

How we use it (POOL bucket / queue-picker):

```python
def dispatch_pool(pool_dir: Path, pool_size: int):
    # Spawn N workers, each running an agentic_loop with the same prompt template
    workers = [
        mcp__clever_lama__agentic_loop(
            goal=f"Pick next item from {pool_dir}/pending/, work it, move to done/ or failed/, repeat until empty.",
            max_iterations=20,  # safety cap per worker
        )
        for _ in range(pool_size)
    ]
    # Wait for all workers to exit (pool empty)
```

Replaces ~260 LOC of bespoke picker + worker + reaper. The atomic-rename mechanism still applies — agents do that as part of their loop body.

### `mcp__clever-lama__verify_with_uncertainty` — chunk-success verifier

What it does: Algorithm 1 from arxiv 2502.15845 — sample N answers, cluster, compute `s_self ∈ [0, 1]` (1 = perfect consensus, 0 = wild divergence). Threshold to decide "trust this result" vs "needs verification".

How we use it (merge step):

```python
# Before consolidating a chunk's fragments, verify the chunk actually succeeded
result = mcp__clever_lama__verify_with_uncertainty(
    question=f"Did chunk {chunk_id} ship correctly? Inspect the commit + paired tests.",
    n_samples=3,
)
if result["s_self"] > 0.5:  # high uncertainty
    # Don't consolidate — flag for manual review
    move_to_review(chunk_id)
```

This was NOT in the original plan. clever-lama gives us deterministic "did this chunk really succeed?" verification, replacing operator-eyeball checks.

### `mcp__clever-lama__recall_learnings` + `recall_semantic` — cross-plan learning

What it does: FTS5 + semantic search across the 892-row learnings table (every prior tool call persists here).

How we use it (CHECKLIST renderer + future plan-init):

```python
# In _plan_render.py — surface relevant past learnings in CHECKLIST.md
similar_plans = mcp__clever_lama__recall_semantic(
    query=plan["scope"], top_k=5
)
# Render under "## Related past work" in CHECKLIST.md
```

And at plan-init time:

```python
# In _plan_init.py (future) — pre-fill scope context from past plans
prior = mcp__clever_lama__recall_semantic(query=user_scope_request, top_k=10)
# Suggest: "You ran a similar plan 3 weeks ago — here's what worked / what failed"
```

This was NOT in the original plan. Adds cross-plan continuity for free.

### `mcp__clever-lama__parallel_grep` — pre-flight conflict detection

What it does: runs `grep` across N paths in parallel, returns matches per path.

How we use it (`_plan_check.py`):

```python
# Cross-chunk ownership collision check
all_owned = collect_owned_paths(chunks)
collisions = mcp__clever_lama__parallel_grep(
    pattern="|".join(re.escape(p) for p in all_owned),
    paths=[c["yaml_file"] for c in chunks],
)
# Any path appearing in >1 chunk's match list = ownership collision
```

Replaces ~50 LOC of bespoke `Counter` + glob walking.

### `mcp__clever-lama__parallel_bash` — alt for queue-picker

What it does: runs N bash commands in parallel. The literal `xargs -P N` shape from `QUEUE_PICKER_BRAINSTORM.md`.

How we use it (alternative POOL implementation):

```python
# Each "worker" is a bash command running clever-lama's subagent CLI
cmds = [f'clever-lama subagent --prompt "$(cat {item}.yaml)"' for item in pool_pending]
results = mcp__clever_lama__parallel_bash(commands=cmds, max_parallel=5)
```

KISS alternative when we don't need the `agentic_loop` autonomy.

## What's STILL bespoke (no clever-lama equivalent)

| Component | Why bespoke |
|---|---|
| `_plan_loader.py` (~80 LOC) | Mode B glob resolution; YAML-specific |
| `_merge_handlers.py` (~300 LOC) | Kit-specific merge actions (consolidate_perms, append_progress, retrofit, cross_pollinate) |
| `_plan_render.py` (~150 LOC) | Kit-specific CHECKLIST.md format |
| Worktree orchestration (~80 LOC) | git is git; thin wrapper |
| `_plan_check.py` validator core (~100 LOC) | Cross-chunk validation logic; reuses `parallel_grep` for the heavy lift |
| `_plan_cli.py` (~100 LOC) | argparse dispatcher for the 6 subcommands |

**Bespoke total: ~810 LOC** of glue logic. Plus ~30+30+50 LOC of clever-lama wrappers. **Grand total ~920 LOC** (vs the originally estimated 980 LOC; net savings smaller than first thought because some bespoke logic is still needed for the kit's specific contracts).

## Honest re-assessment

The savings aren't as large as the "tool map" suggests. Most of the kit is **schema + merge handlers + CLI** — those are kit-specific and don't have clever-lama equivalents. The clever-lama wins are concentrated in:

- **Dispatch primitives** (`parallel_subagents`, `chain_subagents`, `agentic_loop`) — biggest single saving (~200 LOC of orchestration we don't have to write)
- **Verification** (`verify_with_uncertainty`) — capability we wouldn't have built ourselves
- **Cross-plan learning** (`recall_semantic`) — capability we wouldn't have built ourselves

Updated plan-of-record: build the schema + merge layer + CLI bespoke (matches the kit's specific contracts); wire dispatch + verify + recall to clever-lama tools.

## Migration path (revised from OPTIMAL_SYSTEM.md)

| Order | Component | LOC | Notes |
|-------|-----------|-----|-------|
| 1 | `_plan_loader.py` | ~80 | Stdlib + PyYAML; resolves Mode B globs |
| 2 | `_plan_check.py` validator | ~100 | Uses `parallel_grep` for cross-chunk scan |
| 3 | `_plan_dispatch.py` wrapper | ~30 | Just calls `parallel_subagents` |
| 4 | `_merge_handlers.py` (first 4 actions) | ~150 | consolidate_perms + append_progress + dispatch_backlog + render_checklist |
| 5 | `_plan_render.py` | ~150 | CHECKLIST.md; uses `recall_learnings` for past-work section |
| 6 | `_plan_cli.py` | ~100 | argparse dispatcher (check/dispatch/merge/status) |
| 7 | `_merge_handlers.py` (remaining actions) | ~150 | wire_mcp_mounts + retrofit + cross_pollinate + cleanup + commit + verify |
| 8 | `chain_subagents` wrapper for TIER_CHAIN | ~30 | If/when a TIER_CHAIN plan exists |
| 9 | `agentic_loop` wrapper for POOL | ~50 | If/when a POOL plan exists |
| 10 | `verify_with_uncertainty` integration | ~40 | Optional — adds chunk-success verification to merge |

**Phase 1 (items 1-6) = ~610 LOC.** That's the minimum to dispatch + merge + render. Done in 1-2 sessions.

**Phase 2 (items 7-10) = ~270 LOC.** Adds modes + verification. Build when actually needed.

## What about kit-specific MCP tools?

We could WRAP the kit itself as an MCP server (`kaizen-plan-mcp`), exposing tools like `mcp__kaizen-plan__check` / `dispatch` / `merge` / `status`. Defer until the kit is proven on ≥3 real plans (D9 YAGNI). For now, ship as a Python CLI.

## TL;DR

clever-lama's `parallel_subagents` + `chain_subagents` + `agentic_loop` collapse the kit's dispatch layer from ~430 LOC to ~110 LOC. `verify_with_uncertainty` + `recall_semantic` add capabilities we wouldn't have built. **Build the bespoke glue (~600 LOC for Phase 1); wire to clever-lama for everything else.** Same operator surface, half the runtime LOC, more capabilities.
