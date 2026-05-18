# Wave-mode walkthrough — 20 chunks × 5 per wave × 4 rotations

> **Scenario:** plan has 20 chunks, dispatcher slots are capped at 5 concurrent agents, so dispatch as 4 waves of 5 with a merge between each wave.

## TL;DR — what works, what doesn't

| Phase                  | Works today?        | Notes                                                       |
|------------------------|---------------------|-------------------------------------------------------------|
| Pre-flight             | ❌ no conflict detector | Operator eyeballs 20 chunks for ownership collisions       |
| Wave dispatch          | ⚠️ partial — parent agent must hand-write 5 Agent() prompts per wave | Schema declares `wave_size` but no dispatcher consumes it    |
| In-wave wait barrier   | ✓ Agent tool returns on completion | Parent collects 5 results before proceeding              |
| Inter-wave merge       | ❌ no partial-merge mode | Operator runs handlers by hand (and handlers are vaporware) |
| Cross-wave deps        | ⚠️ honored implicitly via wave ordering | No dispatcher enforces dep-respecting wave assignment       |
| Failure recovery       | ❌ no policy        | Operator decides ad hoc whether to proceed / re-run          |
| Final merge            | ❌ all handlers vaporware | Operator runs all 12 merge actions by hand                 |

**Verdict:** the wave shape is REPRESENTABLE in the kit (`concurrency_mode: "waves"`, `wave_size: 5`) but EXECUTING it requires ≥70% manual plumbing. The kit's runtime gap (per `PRE_DISPATCH_AUDIT.md`) hits hardest in wave mode because the orchestrator has more state to track than full-parallel.

## The plan-side declaration (works today)

```yaml
# plan.yaml additions for wave mode
concurrency_mode: "waves"
wave_size: 5
# (Implicit: chunks are batched in chunk-id order. Wave 1 = chunks 1-5, etc.)
```

Optional explicit assignment (NOT in current schema — gap noted below):

```yaml
# Proposed addition
wave_assignment:
  wave_1: [chunk-1, chunk-2, chunk-3, chunk-4, chunk-5]
  wave_2: [chunk-6, chunk-7, chunk-8, chunk-9, chunk-10]
  wave_3: [chunk-11, chunk-12, chunk-13, chunk-14, chunk-15]
  wave_4: [chunk-16, chunk-17, chunk-18, chunk-19, chunk-20]
```

Without explicit assignment, the dispatcher batches by id-order, which often (but not always) matches dep order.

## Concrete walkthrough — 4 waves

### Pre-flight (one-time, before wave-1)

```bash
# 1. Validate schemas (manual — no `kaizen-plan check` yet)
python3 -c "
import json, yaml, jsonschema
plan = yaml.safe_load(open('plan.yaml'))
schema = json.load(open('docs/.../master-plan.schema.json'))
jsonschema.validate(plan, schema)
"

# 2. Eyeball for cross-chunk ownership collisions (gap — no tool)
python3 -c "
import yaml, glob
owns = []
for f in sorted(glob.glob('chunks/*.yaml')):
    c = yaml.safe_load(open(f))
    owns.extend((c['id'], p) for p in c['owns']['scripts'] + c['owns']['tests'] + c['owns']['bins'])
# Check for duplicate paths across chunks
from collections import Counter
dups = [p for p, n in Counter(p for _, p in owns).items() if n > 1]
assert not dups, f'Ownership collision: {dups}'
print(f'OK — {len(owns)} owned paths, 0 collisions')
"

# 3. Create 20 worktrees (manual — no orchestrator)
for i in $(seq 1 20); do
    branch=$(yq ".worktree_branch" chunks/chunk-${i}.yaml)
    git worktree add ".claude/worktrees/${branch}" -b "${branch}" master
done
```

### Wave-1: dispatch chunks 1-5

Parent agent (or human-orchestrator):

```python
# Hand-write 5 Agent prompts (gap — no prompt generator)
prompts = [render_prompt(yaml.safe_load(open(f"chunks/chunk-{i}.yaml"))) for i in range(1, 6)]

# Single message with 5 Agent() calls in parallel
results = [
    Agent(description=f"Coverage chunk-{i}", subagent_type="kaizen-implementer",
          isolation="worktree", prompt=prompts[i-1])
    for i in range(1, 6)
]
# Agent tool returns when each completes; parent collects all 5
```

**Per-chunk effect:**
- Each agent works in its own `.claude/worktrees/<branch>/` (worktree dir)
- Each writes scripts + tests + bins in its `owns:` list
- Each writes fragments to `.chunks/{1..5}/`
- Each commits to its branch
- Each reports completion (or failure) to parent

**Wait barrier:** parent agent waits for all 5 Agent() calls to return before proceeding. The `Agent` tool blocks synchronously per-call; if 5 are dispatched in parallel they all return when each finishes.

### Inter-wave merge (after wave-1, before wave-2)

**Critical decision:** which merge actions run between waves?

Three options:

| Option | Inter-wave actions                                       | Pros                                  | Cons                                       |
|--------|----------------------------------------------------------|---------------------------------------|--------------------------------------------|
| **A**  | Full merge.yaml (all 12 actions)                         | Clean state between waves             | Retrofit runs 4× wastefully                |
| **B**  | Partial merge: consolidate_perms + append_progress + render_master_ledger + render_checklist | Minimal work; defer expensive ops    | Need to split merge.yaml into stages       |
| **C**  | No merge between waves                                   | Simplest                              | `.chunks/` accumulates; no live dashboard  |

**Recommended: B.** But the schema has no concept of "inter-wave merge" vs "final merge". Gap.

**Workaround (manual today):**

```bash
# Inter-wave: run a subset of merge actions
# 1. consolidate_perms (merge .chunks/{1..5}/perms.json into plugin.json)
python3 _merge_handlers.py consolidate_perms   # GAP — handler doesn't exist

# 2. append_progress
for frag in .chunks/{1..5}/progress.md; do
    cat "$frag" >> .kaizen/workflow/progress.md
done

# 3. render_master_ledger (concat ledgers)
cat .chunks/{1..5}/ledger.jsonl >> ledger/MASTER.jsonl

# 4. render_checklist  # GAP — handler doesn't exist

# 5. Merge wave-1 branches to master
for branch in $(yq ".worktree_branch" chunks/chunk-{1..5}.yaml); do
    git merge "$branch" --no-ff -m "merge wave-1: $branch"
done

# 6. DO NOT cleanup_fragments yet — keep .chunks/{1..5}/ for dashboard visibility
# 7. DO NOT run retrofit / cross_pollinate yet — wait for all 20 chunks to exist
```

After this inter-wave merge:
- `plugin.json` has wave-1's 5 chunks' perms
- `progress.md` has wave-1's arch rows
- `ledger/MASTER.jsonl` has wave-1's 5 chunks' tick history
- `CHECKLIST.md` shows wave-1 done, waves 2-4 pending
- `.chunks/{1..5}/` still on disk (for visibility)

### Wave-2 dispatch (chunks 6-10)

Same shape as wave-1. Worktrees already exist (created in pre-flight). Hand-write 5 more prompts. Dispatch. Wait. Merge branches. Inter-wave merge subset. Refresh checklist.

### Waves 3 & 4

Same.

### Final merge (after wave-4)

NOW run the deferred actions:

```bash
# Run remaining merge actions (the "deferred work" tier)
python3 _merge_handlers.py retrofit            # GAP — handler doesn't exist
python3 _merge_handlers.py cross_pollinate     # GAP
python3 _merge_handlers.py cleanup_fragments   # rm -rf .chunks/
python3 _merge_handlers.py merge_commit
python3 _merge_handlers.py final_verify
python3 _merge_handlers.py render_checklist    # final refresh
```

Single merge commit captures the cross-wave consolidation work.

## Wave-mode-specific gaps (beyond the general audit)

### W1. No partial-merge stage in schema

`merge.yaml` is one flat actions list. Wave mode wants TWO lists:
- inter-wave actions (consolidate + log + ledger + checklist)
- final actions (the above PLUS retrofit + cross_pollinate + cleanup + commit + verify)

**Fix:** add `merge.stages:` to schema, OR a sibling `interwave_merge.yaml` file referenced by plan.yaml. Either supports `kaizen-plan merge --stage interwave` vs `kaizen-plan merge --stage final`.

### W2. `wave_size` declared but not consumed

`concurrency_mode: "waves"` + `wave_size: 5` is schema-valid but no dispatcher reads it. Operator manually batches Agent() calls 5-at-a-time.

**Fix:** `kaizen-plan dispatch --plan plan.yaml --wave N` returns the N-th batch of chunk dispatches (5 chunks at a time).

### W3. No explicit wave assignment

Schema implicitly batches by chunk id order. If wave-2 chunks depend on wave-1 outputs, that's coincidental — schema doesn't verify it.

**Fix:** add `wave_assignment:` field (proposed above) + validator that asserts no chunk depends on a chunk in a later wave.

### W4. No cross-wave dep checker

`deps: [chunk-3]` in chunk-12 (wave-3) requires chunk-3 (wave-1) to be merged first. Wave ordering enforces this implicitly. But if operator mis-assigns chunk-12 to wave-1 (alongside chunk-3), they'd parallel-execute despite the dep.

**Fix:** pre-flight: `assert chunk.deps[i].wave < chunk.wave for every dep`.

### W5. Inter-wave failure recovery undefined

Wave-1 has 4 successes + 1 failure (chunk-3). Policy choices:
- ABORT — don't run inter-wave merge, don't dispatch wave-2; fix chunk-3, re-dispatch
- PARTIAL — inter-wave-merge the 4 successes, leave chunk-3 in pending, dispatch wave-2 in parallel with chunk-3 retry
- DEFER — inter-wave-merge the 4, skip chunk-3, dispatch wave-2; chunk-3 retried in a later wave

**Fix:** add `failure_policy:` field to plan.yaml — `abort` / `partial` / `defer`.

### W6. Token budget per-wave aggregation

Per chunk: 30k. Per wave (5 chunks): 150k. Plus inter-wave merge: ~22k. 4 waves: 4 × (150k + 22k) = 688k total.

Operator should know this BEFORE dispatching wave-1. No plan-level total budget.

**Fix:** add `total_budget_tokens` field (auto-computable from `sum(chunks.budget_tokens) + N × merge.budget_tokens`).

### W7. Worktree lifecycle across waves

20 worktrees created in pre-flight. After wave-1 inter-wave merge, the 5 wave-1 branches are merged to master — but the worktrees still exist. Disk: ~10GB cumulative.

**Fix:** `kaizen-plan cleanup-worktrees --merged-only` after each inter-wave merge to reclaim disk (worktrees of merged branches are safe to delete).

### W8. Checklist render between waves shows partial state

`render_checklist` works fine between waves IF the handler exists (it doesn't). When it lands, the checklist after wave-1 should show:
- Wave-1 chunks: rollup of done / skipped / failed
- Waves 2-4: all `pending`
- Plan-level: 25% complete

Currently CHECKLIST.example.md doesn't show this intermediate state — only the after-all-waves snapshot.

**Fix:** extend the render to include a `## Wave progress` section showing per-wave rollup.

## Operator runbook (manual, today)

Given the gaps, here's what an operator actually does:

```
PRE-FLIGHT
  ├─ author plan.yaml + 20 × chunks/*.yaml
  ├─ run jsonschema validation (manual python -c)
  ├─ eyeball cross-chunk ownership for collisions (manual python -c)
  ├─ create 20 worktrees (for loop in bash)
  └─ run rubric to confirm wave-mode choice (kaizen-rubric eval)

WAVE-N (repeat for N = 1, 2, 3, 4)
  ├─ hand-write 5 Agent() prompts from chunks/chunk-{N*5-4 .. N*5}.yaml
  ├─ single message: 5 Agent() calls in parallel
  ├─ wait for all 5 to return (Agent tool blocks)
  ├─ if any failed: ABORT here, fix, re-dispatch only the failed
  ├─ git merge 5 branches to master
  ├─ INTER-WAVE MERGE (manual — handlers don't exist):
  │   ├─ python3: consolidate .chunks/{N*5-4..N*5}/perms.json → plugin.json
  │   ├─ bash:    cat .chunks/{}/progress.md → progress.md
  │   ├─ bash:    cat .chunks/{}/ledger.jsonl → ledger/MASTER.jsonl
  │   ├─ (skip render_checklist — no handler)
  │   └─ git commit -m "merge wave-N"
  └─ proceed to wave-(N+1)

FINAL MERGE (after wave-4)
  ├─ retrofit selected axes to YAML (manual decision + edits)
  ├─ run new axes against semantic-search (manual)
  ├─ rm -rf .chunks/ (manual cleanup)
  ├─ git commit -m "final merge"
  ├─ python3 -m unittest discover (final verify)
  └─ (optional) render CHECKLIST.md by hand
```

**Token cost estimate** (for the operator's planning):

| Phase                           | Tokens (rough)          |
|---------------------------------|-------------------------|
| Each agent in a wave            | 25-35k                  |
| 5 agents per wave               | 125-175k                |
| Inter-wave merge (operator's parent context) | ~5-10k     |
| 4 waves                         | 4 × 150k + 4 × 7.5k = ~630k |
| Final merge                     | ~22k (or much more if all handlers run by hand) |
| **TOTAL**                       | **~650-700k**           |

## Wave-mode-only improvements (priority-ordered)

If the kit's runtime were to be built, here's the order that helps wave mode specifically:

| Order | Gap                           | Time-to-fix | Impact                                  |
|-------|-------------------------------|-------------|------------------------------------------|
| 1     | W2 — `kaizen-plan dispatch --wave N` | small      | Removes the "hand-write 5 prompts × 4" toil |
| 2     | W1 — `merge.stages` (or two yamls)   | small      | Enables partial-merge between waves      |
| 3     | W5 — `failure_policy` field          | small      | Makes failure handling deterministic     |
| 4     | W7 — `cleanup-worktrees --merged-only` | small    | Disk hygiene                             |
| 5     | W3 + W4 — explicit wave assignment + dep checker | medium | Catches dep-ordering bugs pre-flight    |
| 6     | W8 — checklist with wave-progress section | medium  | Operator dashboard                       |

Items 1-4 are all small (≤100 LoC each). Together they make wave mode usable without hand-rolling 70% of the plumbing.

## Honest assessment for the 20-chunk × 4-wave scenario

**Today:** an operator CAN run this, but ~50% of their cognitive load is on the orchestration ritual (worktrees, prompt drafting, inter-wave merges, branch merges) rather than on the actual work the chunks produce. At 5 chunks the toil is tolerable; at 20 chunks across 4 waves it's the bottleneck.

**With items 1-4 above:** the ritual collapses to:
```bash
for wave in 1 2 3 4; do
    kaizen-plan dispatch --plan plan.yaml --wave $wave  # spawns 5 agents
    # (operator waits)
    kaizen-plan merge --plan plan.yaml --stage interwave
done
kaizen-plan merge --plan plan.yaml --stage final
```
~6 commands for a 20-chunk plan. That's the target.

**Recommendation:** if a real 20-chunk × 5-wave plan is imminent, build items 1-4 first as a small kaizen skill (`plugins/kaizen/skills/parallel-branches/`). Spec without runtime works at 5 chunks; wave mode at 20 chunks needs the runtime.
