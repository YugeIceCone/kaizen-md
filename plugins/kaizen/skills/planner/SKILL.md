---
name: planner
description: Drives the superpowers-family chain end-to-end — brainstorm → spec → plan → tasks → execute — as a single orchestrated pass. Use when the user wants the full pipeline ("from idea to PR", "plan the whole thing", "drive the chain"), not a single stage. Routes through brainstorming, create-plan, create-tasks, and execute-plan or subagent-driven-development in order, skipping stages whose artifact already exists. Lighter than `kaizen:workflow schema=spec-driven` (which is EARS-notation + 6 ceremony phases); heavier than calling each skill individually. Pairs with brainstorming / create-plan / create-tasks / execute-plan / subagent-driven-development / supervisor. Triggers on "drive the chain", "end-to-end plan", "from idea to PR", "full pipeline", "spec to code", "planner", "brainstorm to execute", "plan and run", "orchestrate plan", "chain the skills".
metadata:
  version: "1.0"
  origin: kaizen-md 2026-05-20 (gap surfaced by skill-flow trace — item 24 of the unify-artifact-generation blueprint)
---

# Planner — drives the superpowers chain end-to-end

The six superpowers-family skills each do one job well. None of them
own the **chain itself**. When the user says "plan this and ship it"
nobody is responsible for routing through brainstorming → create-plan →
create-tasks → execute. This skill is that router.

## What this skill IS

A thin orchestrator that walks the canonical chain in order, skipping
stages whose output artifact already exists, and producing one durable
blueprint.json at the end. Five linear stages, each delegating to an
existing skill — this skill never duplicates their logic.

## What this skill is NOT

- **Not a replacement for** brainstorming / create-plan / create-tasks
  / execute-plan / subagent-driven-development. Those skills own their
  stage logic. This skill orchestrates *which* runs *when*.
- **Not `kaizen:workflow schema=spec-driven`** — that's EARS-notation +
  Decision Records + 6 ceremony phases. Use it for medium-to-high-risk
  work that needs formal traceability. Use *this* skill for the lighter
  superpowers shape.
- **Not `kaizen:supervisor`** — supervisor decides the next stage
  inside an in-session run; planner is the canonical chain for
  brainstorm-to-execute work specifically.

## The chain

Schema-driven via `schemas/planner/schema.yaml`. Dispatched as a
routine via `/workflow schema=planner` OR invoked directly via
`Skill(kaizen:planner)`.

```
[brainstorm?]               → spec   (kind=spec)  — OPTIONAL prequel
   ↓
create-plan                 → plan   (kind=plan, blueprint.json)
                            ↑ CANONICAL ENTRY POINT
                            ↑ DUAL GATE: QA pass + explicit user trigger
   ↓
create-tasks                → tasks  (kind=task-list inside plan)
   ↓
execute                     → commits
                            ↑ DUAL GATE: QA pass + explicit user trigger
   Mode A: execute-plan      (sequential, in-place)
   Mode B: subagent-driven-development  (parallel, per-task subagent)
   ↓
verify                      → GO / NO-GO  (verify-before-execution)
```

**Canonical entry is `create-plan`, not `brainstorm`.** Brainstorming
is an optional prequel when the user's request is ill-formed; skip it
when the request is concrete enough to plan directly. Completion of
`create-plan` is what triggers the rest of the chain forward — this is
the rule encoded in `schema.yaml::apply.gate: create-plan`.

## Dynamic dispatch

The chain ADAPTS based on runtime state. On each invocation, walk the
entry-point rules (first match wins) and start at the first stage
whose `enter_when` holds:

| Entry stage | Enter when |
|---|---|
| `execute` | Plan exists AND tasks[] populated AND no recent commits — RESUME case |
| `create-tasks` | Plan exists AND tasks[] empty — task creation needed |
| `brainstorm` | User prompt is exploratory ("could we", "what if") |
| `create-plan` | DEFAULT — any other concrete request without an existing plan |

**Skip rules:** any stage whose output artifact already exists at its
canonical location AND has status ∈ {active, shipped} is skipped. The
runner ticks past it.

**Branch rule at `execute`:** if the plan's `dispatch.mode` is
`parallel` or `waves`, route to `subagent-driven-development`. Otherwise
`execute-plan` (sequential, default).

## Chunking (default) + subagent dispatch (opt-in)

### Default — parent executes, 3 tasks per chunk

Without explicit subagent opt-in, the parent walks the task-list 3
tasks at a time. The 3-task chunks give natural commit + verify
boundaries between batches. No `Agent()` dispatch, no worktree
overhead, no merge step.

```bash
kaizen-blueprint chunk --list-id <list-id>
```

Output: `bucket=PARENT_DOES_IT`, chunks of 3 in order, dispatch hint
`mode=sequential isolation=inline agent=None`. The parent picks
chunk 1, completes its 3 tasks, commits + verifies, then chunk 2, etc.

### Opt-in — subagent dispatch via the D2 rubric

When concurrency wins (independent tasks, isolation needed), opt in:

```bash
kaizen-blueprint chunk --list-id <list-id> --subagents
```

The parallel-branches kit's chunking-floor rubric (D2) applies:

| In-flight tasks | Bucket | Dispatch shape |
|---|---|---|
| ≤3 | `PARENT_DOES_IT` | Still no dispatch — setup cost > work cost |
| 4–6 | `ONE_SUBAGENT` | One `Agent()` call in a worktree |
| 7–30 | `GRID` | `ceil(n/3)` parallel chunks via `subagent-driven-development` |
| 31+ | `POOL` | Queue-picker — `parallel_subagents` MCP in clever-lama-mcp |

**Chunking output IS the dispatch plan.** Each chunk lists 2-3 task
IDs that one subagent owns. The parent dispatches all chunks in a
single message (when bucket=GRID) — same wave, multiple `Agent()`
calls — and runs the merge step after all chunks settle.

**The parallel-branches kit's 10 disciplines (D1–D10) all apply at
GRID + POOL:**

- D1: every value explicit — never imply
- D2: chunking floor 2-3 items
- D3: line caps not token caps
- D4: parallel-safe by construction (no two agents write same file)
- D5: merge is single-writer + always last
- D6: conflict pre-flight non-negotiable (`kaizen-parallel-dispatch-audit`)
- D7: schema-validated end-to-end
- D8: KISS over capability
- D9: YAGNI over speculation
- D10: Boy-Scout in-kit

Read the kit's reference docs at
`.kaizen/docs/templates/parallel-branches-DISCIPLINES.md` before any
GRID or POOL dispatch.

**Per-subagent prompt template** (when bucket=GRID): use the
chunk-plan template at
`.kaizen/docs/templates/chunk-plan-template.md`. Each subagent gets:
1. The parent's blueprint path
2. Its 2-3 task IDs (from `chunk_tasks()` output)
3. The dispatch_hint (isolation=worktree, agent=kaizen-implementer)
4. The kit's DISCIPLINES.md reference

## ⚠ Dual-gate at create-plan AND execute

Two stages require BOTH a QA pass + explicit user trigger before
they run. NO autonomous proceed:

### Gate 1 — `create-plan`

Before drafting the plan:

1. **QA pass** — AskUserQuestion to disambiguate:
   - Scope (what's in / out)
   - Unstated constraints (deadlines, dependencies, blast radius)
   - Artifact location (`.kaizen/docs/<YYYY-MM-DD>-<topic>/` confirmed?)
   - Plan-kind (single-file blueprint? sub-plans linked DAG?)
   Surface a one-paragraph plan summary before triggering.

2. **User trigger** — explicit. "create the plan", "go ahead", "draft
   the plan", "/kaizen:planner go". An "ok" after a status report is
   NOT a trigger. The user must direct create-plan specifically.

### Gate 2 — `execute`

Before implementing:

1. **QA pass** — AskUserQuestion to confirm:
   - Execution mode (A sequential vs B parallel)
   - Task batch (all / first-N / specific IDs)
   - Flags / env knobs to apply
   - Side-effects to acknowledge (cron, pushes, deletions)

2. **User trigger** — explicit. "execute the plan", "run the tasks",
   "implement these", "/kaizen:planner execute". Status reports + "ok"
   don't count; execution is destructive.

**Why dual-gate at these two stages and nowhere else:** brainstorming
is exploratory (no destruction); create-tasks operates inside an
already-approved plan (low-blast-radius edits to a blueprint);
verify is non-destructive RED-GREEN. Only `create-plan` (creates a
durable artifact the user commits to) and `execute` (mutates code) are
worth pausing for. Pausing everywhere = ceremony; pausing nowhere =
silent runaway.

## When to use this skill

- User says "from idea to PR" / "plan and ship" / "drive the whole chain".
- A vague feature request with no spec, no plan, no tasks yet.
- A formal pipeline gate (e.g. monthly planning sweep) wants disciplined
  artifact lineage.

## When NOT to use this skill

- User has a concrete one-line change ("rename X to Y") — use `task` directly.
- User has an existing plan and just wants execution — use
  `execute-plan` or `subagent-driven-development` directly.
- The work is medium-to-high risk and needs EARS-notation traceability
  — use `/workflow schema=spec-driven` instead.

## How to run

### 1. Establish state

Before dispatching ANY stage:

- Check `.kaizen/docs/` for an existing `<date>-<topic>-design.md` spec.
- Check `.kaizen/docs/<YYYY-MM-DD>-<topic>/plan.{md,json}` for an existing plan.
- Read either if found; note their `status` (draft / active / shipped).

### 2. Dispatch in order

For each stage the chain hasn't already finished:

1. Load the stage's skill (e.g. `Skill(brainstorming)`).
2. Run it. Capture the artifact it produces.
3. Confirm the artifact landed at the canonical location.
4. Move to the next stage.

### 3. Output one blueprint

The chain's deliverable is ONE blueprint.json at
`.kaizen/docs/<YYYY-MM-DD>-<topic>/plan.json` containing:

- `kind=plan` root item linked to its `kind=spec` via `links.parents`.
- One or more `kind=task-list` items with populated `tasks[]`.
- Optional `kind=decision` items for locked choices.
- `session_meta.cc_session_uuid` filled.
- `outcome` and `outcome_justification` on terminal items.

Validate against
`.kaizen/docs/templates/blueprint.schema.json` before declaring done.

### 4. Hand off

If a context boundary hits mid-chain, invoke `kaizen:handoff` to
preserve resume state. The next session re-enters planner; the chain
auto-skips finished stages.

## Cross-references

- `brainstorming` — stage 1; produces spec
- `create-plan` — stage 2; produces blueprint plan
- `create-tasks` — stage 3; populates task-lists inside the blueprint
- `execute-plan` — stage 4 (sequential path); in-place plan mutations
- `subagent-driven-development` — stage 4 (parallel path); commit-per-task
- `verify-before-execution` — stage 5; iron-law RED-GREEN gate
- `supervisor` — when the chain isn't the right shape (replan, pause)
- `workflow` — when EARS-notation traceability is needed (use `schema=spec-driven` instead)
- `.kaizen/docs/templates/blueprint.schema.json` — the artifact format
- `.kaizen/docs/plans/2026-05-20-unify-artifact-generation.json` — example blueprint authored without this skill, but shaped like one

## Anti-patterns

- **Re-deriving stage logic** — never. If brainstorming's body says
  "save to `.kaizen/docs/`", trust it. Don't add planner-specific
  variants of stage instructions.
- **Skipping verify-before-execution** — the final gate is non-optional.
  Every stage's output is a candidate for RED-GREEN proof before the
  chain hands off.
- **Running stages in parallel** — the chain is causal. Stage N reads
  stage N-1's output. Parallelization happens INSIDE a stage (via
  subagent-driven-development at stage 4), not between stages.
- **Inventing new stage names** — if a stage doesn't fit the 5
  canonical ones, the work probably isn't a planner job. Use
  `kaizen:workflow` (it has 17 schema-driven routines) or
  `kaizen:supervisor` (for free-form orchestration).
