# Pre-dispatch audit — 20-agent readiness

## TL;DR

If I had to dispatch 20 parallel `Agent()` calls **right now**, I'd hit ≥6 blockers. The schemas + examples exist but the **runtime is largely vaporware** — no loader, no prompt generator, no worktree orchestrator, no merge-action handlers, no conflict pre-flight. Operators would hand-roll all of it.

Severity at a glance:

| # | Gap                                                    | Severity      | Blocks dispatch?                |
|---|--------------------------------------------------------|---------------|----------------------------------|
| 1 | `_plan_loader.py` doesn't exist                        | **CRITICAL**  | Yes — Mode B unrunnable          |
| 2 | No prompt generator (chunk → Agent prompt)             | **CRITICAL**  | Yes — operator writes 20 by hand |
| 3 | No worktree orchestrator (create + cleanup × 20)       | **CRITICAL**  | Yes — manual `git worktree add` × 20 |
| 4 | No pre-flight conflict detector                        | **CRITICAL**  | Likely — silent ownership collisions ship |
| 5 | All `merge.actions[]` handlers are vaporware           | **CRITICAL**  | Yes — MERGE can't run            |
| 6 | Auto-handoff trigger not wired                         | **HIGH**      | Borderline — T3-sized chunks fail  |
| 7 | Handoff parentage not modeled in ledger                | **HIGH**      | MASTER.jsonl can't link siblings |
| 8 | No schema uniqueness enforcement (cross-chunk)         | **MEDIUM**    | Silent collision (caught at runtime) |
| 9 | No DAG / mermaid visualizer                            | **LOW**       | Cognitive only                   |
| 10| Rubric coverage gaps (10 < items < 20 falls through)   | **LOW**       | Falls back to NEEDS_AGENT        |

This file documents each gap + the minimum mitigation to ship a real 20-agent run.

---

## CRITICAL — runtime vaporware (5 items)

### 1. Loader (`_plan_loader.py`) missing

**Symptom:** plan.yaml says `chunks: "./chunks/*.yaml"`. Nothing resolves that glob. Validator / dispatcher / rubric all expect `chunks: [<chunk>, ...]` after loader normalization.

**Minimum fix** (≤80 lines stdlib + PyYAML):
```python
# plugins/kaizen/skills/workflow/scripts/_plan_loader.py
import yaml
from pathlib import Path

def load_plan(path: Path) -> dict:
    base = path.parent
    plan = yaml.safe_load(path.read_text())

    if isinstance(plan.get("chunks"), str):
        plan["chunks"] = sorted(
            yaml.safe_load(p.read_text())
            for p in base.glob(plan["chunks"].removeprefix("./"))
        )

    if isinstance(plan.get("merge"), str):
        merge_path = base / plan["merge"].removeprefix("./")
        plan["merge"] = yaml.safe_load(merge_path.read_text())

    return plan
```

**Pairing:** add `tests/test_plan_loader.py` covering Mode A passthrough + Mode B glob resolution + relative-path edge cases.

### 2. Prompt generator (chunk → Agent prompt) missing

**Symptom:** every chunk has Guide / Tasks / Plan / Isolation contract. The dispatch prompt that goes to `Agent(prompt=...)` must assemble these into a single string. Without a generator, operators copy/paste from chunk YAML into 20 Agent calls — error-prone, drift-prone, no validation that the prompt actually surfaces the isolation contract.

**Minimum fix:** `kaizen-plan render-prompt --chunk chunks/chunk-N.yaml` emits the canonical Agent prompt. Template:

```
Implement chunk {id} of {plan_path}.

WORKING DIR: {guide.working_dir}

READ FIRST (in order):
1. {plan_path}::{id}
2. docs/superpowers/templates/chunk-plan-template.md (4-section shape + isolation contract)
{for f in guide.exemplar_files: f}

SKILLS TO LOAD (before any edit): {guide.skills_to_load | join(", ")}

ISOLATION CONTRACT (read carefully):
- Owns: {owns.scripts + owns.tests + owns.bins + owns.fragment_dir}
- NEVER write: plugin.json, progress.md, backlog.json, gateway.py — fragments to {owns.fragment_dir} only.

EXECUTE: Task list (checklist), items {tasks[].id | join(" → ")} in order.
{for t in tasks: "  - " + t.id + ": " + t.description}

DONE WHEN: every paired test green; full suite 0 regressions; .chunks/{id}/ fragments present.

BUDGET: ~{budget_tokens}. If exhausted, commit green items + write {fragment_dir}resume.md.
```

### 3. Worktree orchestration missing

**Symptom:** 20 chunks → 20 worktrees. No tool creates them or cleans them up. Manual sequence per chunk:
```bash
git worktree add .claude/worktrees/<chunk-id> -b <worktree_branch> master
```
20 chunks × hand-rolled = 20 chances to typo a branch name.

**Minimum fix:** `kaizen-plan dispatch --create-worktrees --plan plan.yaml` walks `chunks[]`, creates worktrees in batch. Also `kaizen-plan cleanup --merged-only` removes worktrees whose branches landed on master.

**Disk-space audit:** 20 × ~500MB worktree = ~10GB. Operator needs to check `df -h` before dispatch.

### 4. Pre-flight conflict detector missing

**Symptom:** schema doesn't enforce uniqueness across chunks. Two chunks both owning `skills/workflow/scripts/foo.py` would silently overwrite at merge time. Failure modes:
- Same `worktree_branch` → second `git worktree add` fails
- Same `owns.scripts/tests/bins` path → both write, last-merge-wins, silent overwrite
- Same `fragment_dir` → fragment overwrites
- `deps:` referencing non-existent chunk id
- Cycle in `deps:` (chunk-A→chunk-B→chunk-A)

**Minimum fix:** `kaizen-plan check --plan plan.yaml` runs:
- jsonschema against master-plan + chunk schemas
- collect all `owns.{scripts,tests,bins}` across chunks → assert no path appears twice
- collect all `worktree_branch` → assert unique
- collect all `fragment_dir` → assert unique
- walk `deps:` graph → assert no cycles + every ref resolves to a chunk id

Returns canonical envelope; exit 1 on any conflict. Run before dispatch.

### 5. Merge-action handlers are vaporware

**Symptom:** `merge.yaml` declares 12 actions. None of them have code. The MERGE step doc lists pseudo-bash for each, but there's no `kaizen-plan merge --plan plan.yaml` that actually runs them.

**Minimum fix:** `_merge_handlers.py` registry — one handler per action enum:
```python
HANDLERS = {
    "consolidate_perms":    _h_consolidate_perms,
    "append_progress":      _h_append_progress,
    "dispatch_backlog":     _h_dispatch_backlog,
    "wire_mcp_mounts":      _h_wire_mcp_mounts,
    "render_master_ledger": _h_render_master_ledger,
    "render_checklist":     _h_render_checklist,
    "retrofit":             _h_retrofit,           # args: targets
    "cross_pollinate":      _h_cross_pollinate,    # args: to_project, axes
    "cleanup_fragments":    _h_cleanup_fragments,
    "merge_commit":         _h_merge_commit,
    "final_verify":         _h_final_verify,
}
```

Each handler is 20-50 lines. `kaizen-plan merge` iterates `merge.actions[]` in order, dispatches to the matching handler.

`render_checklist` is the highest-value handler — it's the operator dashboard. Build it first.

---

## HIGH — operational gaps that bite

### 6. Auto-handoff trigger not wired

**Symptom:** `chunk-ledger.schema.json` has `status: "handoff"` + `handoff_to` field. Nothing DETECTS that an agent should hand off. The kaizen:auto-handoff hook fires at 85% context threshold (per prior work), but it doesn't know about chunk ledgers — it writes a generic handoff YAML, not a `{chunk_id, item_id, status: handoff}` ledger row.

**Minimum fix:** extend auto-handoff to detect "in a chunk context" (via env var `KAIZEN_CHUNK_ID` set by the dispatcher) and emit a chunk-shaped ledger row instead of generic handoff.

### 7. Handoff parentage not modeled

**Symptom:** when chunk-7 hands off to chunk-7-sibling-b, MASTER.jsonl gets rows under both `chunk-7` AND `chunk-7-sibling-b`. The `render_checklist` action has to know these are the SAME logical chunk. No schema field captures that relationship.

**Minimum fix:** extend `chunk-ledger.schema.json`:
```json
"parent_chunk_id": {"type": "string", "description": "When this is a handoff sibling, points at the parent chunk id"}
```

Sibling agents set `parent_chunk_id: "chunk-7"` on every row they write. The checklist renderer groups by `parent_chunk_id ?? chunk_id`.

---

## MEDIUM — schema lints

### 8. Cross-chunk uniqueness not enforceable in JSON Schema directly

JSON Schema can validate one chunk in isolation but can't say "no two chunks share a worktree_branch". This is fundamental — needs a custom validator (item 4 above does it).

### 9. Conditional required keys

`master-plan.schema.json` says `wave_size` required when `concurrency_mode==waves` only in prose. Schema-enforce via `if/then`:
```json
"allOf": [{
  "if":   {"properties": {"concurrency_mode": {"const": "waves"}}},
  "then": {"required": ["wave_size"]}
}]
```

### 10. Empty fragment files

`perms-fragment.schema.json` has `minItems: 1`. A chunk that adds no new perms (rare but possible — refactor-only chunk) would have to write `[]` which fails validation. Fix: relax to `minItems: 0` OR document "if no perms to add, omit the fragment from `fragments:` list".

### 11. `mcp-mounts.txt` has no schema

Listed in `fragments: enum` but no shape spec. Fix: write `mcp-mounts.schema.json` covering the `("name", "module")` tuple format.

---

## LOW — DX / observability gaps

### 12. No DAG / mermaid visualizer

20 chunks + deps + concurrency in a markdown table is hard to read at a glance. Add `kaizen-plan render-dag --plan plan.yaml` → mermaid flowchart of chunk dependencies.

### 13. Rubric coverage gaps

`chunk-sizing.yaml` has rules for `total_items <= 10` (GRID_5) and `>= 20` (GRID_15). Items 11-19 fall through to NEEDS_AGENT. Add a GRID_10 rule or relax the boundaries.

### 14. No plan-level token-budget cap

Each chunk caps at 40k. 20 chunks × 40k = 800k. No way to declare a plan-level `total_budget_tokens` that the dispatcher could honor (e.g. abort if dispatch would exceed). Add `total_budget_tokens` field to master-plan.

### 15. No `plan_done_when`

Per-chunk `Done when:` is documented but plan-level is implicit. Add `plan_done_when:` array of criteria at the plan level — schema can list the conditions, operator/dashboard can check them.

### 16. Skill-load duplication waste

Each of 20 agents independently loads `kaizen:tdd` (~8k) + `kaizen:plugin-development` (~6k) = 280k tokens spent on duplicate setup across the fleet. No way to share. Mitigation: ensure subagent system prompt pre-loads these once (kaizen-implementer config) — outside this kit's scope but worth noting.

### 17. Backlog dedupe

Two chunks producing identical backlog.jsonl rows = MERGE creates duplicate backlog items. `dispatch_backlog` handler should dedupe by `(title, ref)` before calling `kaizen backlog add`.

### 18. Rubric output not captured in plan.yaml

Operator runs the rubric, gets `bucket: GRID_15`. plan.yaml doesn't record which bucket it chose for traceability. Add `decomposition_rubric_bucket: "GRID_15"` field to master-plan, optionally populated by `kaizen-plan size --plan plan.yaml`.

### 19. No transactional rollback for MERGE failures

If MERGE crashes after `consolidate_perms` but before `merge_commit`, plugin.json is mutated but no commit captures it. Manual cleanup. Mitigation: each handler writes its own commit immediately ("merge step N: consolidate_perms") so partial-MERGE state is recoverable.

### 20. Cross-repo handling

`isolation: none` means no kaizen-md worktree. But chunk 15 still acts on semantic-search — it might need ITS OWN worktree there. Schema doesn't differentiate "no kaizen-md worktree" from "no worktree at all". Add `cross_repo_worktree_branch` field for cross-repo chunks.

---

## What to fix BEFORE a real 20-agent dispatch

Minimum viable path:

| Order | Item | Why first |
|-------|------|-----------|
| 1     | #4 conflict detector + schema lints (#8/#9/#10) | Surfaces silent collisions; fixes today's "schema valid but plan is broken" gap |
| 2     | #1 loader | Without it, Mode B is paper                                                       |
| 3     | #5 merge handlers (start with `consolidate_perms` + `render_checklist`) | Operator-facing critical path  |
| 4     | #2 prompt generator | Avoids 20 hand-rolled prompts that drift from the contract                       |
| 5     | #3 worktree orchestrator | Closes the manual-`git worktree add` × 20 toil                                |
| 6     | #6/#7 auto-handoff + parentage | Required for T3-sized chunks (≥10 items)                                  |

Other items are improvements but not blockers. Ship the 6 above as a `parallel-branches` runtime kit (likely a kaizen skill at `plugins/kaizen/skills/parallel-branches/`) before any real 20-agent dispatch.

## Honest assessment

The kit as it stands is a **strong specification** (schemas, rubric, examples all validated end-to-end) but a **weak runtime** (almost nothing executes). An operator could:
- ✓ author plan.yaml + chunk files
- ✓ validate them schema-wise
- ✗ resolve Mode B globs (no loader)
- ✗ dispatch 20 worktrees + agents (no orchestrator)
- ✗ run the MERGE step (no handlers)
- ✗ generate the CHECKLIST.md dashboard (no renderer)

For a **5-chunk plan** an operator can fake the runtime by hand. For **20 chunks** they can't — toil scales worse than linearly (worktree mgmt + prompt drift + merge conflicts compound).

**Recommended next step:** before doing another "dynamically scale to N chunks" exercise, ship the 6 critical runtime pieces above as actual Python under `plugins/kaizen/skills/parallel-branches/` (or similar). Spec without runtime is theater at this scale.
