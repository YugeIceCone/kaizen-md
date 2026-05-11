# Orchestration: Subagent Modes & Auto-Mode Behavior

How the workflow skill dispatches stages to subagents and handles auto-mode chaining.

## Subagent Mode Decision Table

| Stage | `subagent=no` | `subagent=yes` | `subagent=full` |
|---|---|---|---|
| explore | local | **Explore subagent** | **Explore subagent** |
| detect-stack | local | local | **Explore subagent** |
| research | local | **general-purpose subagent** | **general-purpose subagent** |
| analyze | local | **general-purpose subagent** | **general-purpose subagent** |
| audit | local | **general-purpose subagent** | **general-purpose subagent** |
| review | local | **general-purpose subagent** | **general-purpose subagent** |
| debug | local | local | **general-purpose subagent** |
| create-plan | local | local | local (single source of truth) |
| create-tasks | local | local | local |
| execute-plan | local | local | **per-phase subagents (serial or parallel)** |
| execute-tasks | local | local | **per-task subagents (serial)** |
| fix | local | local | local |
| validate | local | local | **general-purpose subagent** |
| report | local | local | local |

**Rule of thumb:**

- **Read-only stages** (explore, research, audit, analyze, review, validate) — safe to subagent in `yes` and `full`.
- **Plan / task creation** stays local even in `full` — single agent owns the plan-file edits to avoid concurrent writes.
- **Execution stages** subagent only in `full`, and only when the plan declares phase independence.
- **Bundled-command stages** (`simplify`, `batch-fanout`) — invoke Claude Code's own multi-agent runtime (`/simplify` spawns 3 reviewers, `/batch` spawns 5–30 worktree workers). The workflow's `subagent=` flag has **no effect** on these stages: they always run as bundled commands, atomically from the orchestrator's view. Don't try to wrap them in a Task call.

## Custom Agent Routing

The workflow ships four custom agents at `~/.claude/agents/` that the orchestrator should prefer over `general-purpose` for known stage shapes:

| Stage(s) | Custom agent | Why |
|---|---|---|
| explore, detect-stack, research, audit | `wf-explorer` | Read-only, knows routine stage prompts; cheaper than general-purpose for the front of every routine |
| analyze, review, validate, debug, fix, create-plan, create-tasks, execute-tasks, report | `wf-stage` | Knows `.workflow/state.json` and the `advance` protocol — saves prompt boilerplate |
| per-phase parallel execution (subagent=full) | `wf-phase` | Worktree-isolated; reads plan's Resume Protocol; one phase per dispatch |
| batch-migrate.analyze (decomposition into 5–30 units) | `wf-decomposer` | Enforces `/batch`'s independence contract |
| simplify, batch-fanout | (none — bundled commands) | Run as bundled `/simplify` / `/batch`, no subagent |
| review (when deeper) | `superpowers:code-reviewer`, `feature-dev:code-reviewer` | Plugin agents; richer than `wf-stage` for pure review |
| security-flavored audit | `agent-aegis` | Plugin agent; threat-modeling lens |

**Fallback:** if no custom or plugin agent fits, use `general-purpose`.

## Subagent Dispatch Templates

### Read-only stage (explore / research / audit / analyze / review / validate)

```
Use the Agent tool with subagent_type="Explore" (for codebase mapping) or "general-purpose" (for everything else).

Prompt:
  Stage: <stage-name>
  Goal: <one-sentence stage goal pulled from references/routines.md>
  Inputs: <plan_file path if it exists, else describe the request>
  Constraints: read-only; do not modify files.
  Output format: <stage-specific — e.g. for "audit", a numbered findings list with file:line refs>
  Return: a concise summary and the path to any artifact you wrote (if applicable).
```

### Per-phase execution (subagent=full, after plan has Phases marked independent)

```
Use the Agent tool with subagent_type="general-purpose".

Prompt:
  Read plans/<file>.md top to bottom and follow its Resume Protocol.
  Execute Phase <N> ONLY. Do not touch other phases.
  Update Phase <N> Status and Notes in the plan file.
  Stop and return when:
    - Phase <N>'s Verification command passes (Status=complete), OR
    - Phase <N> is blocked (Status=blocked with cause in Notes).
  Return: phase outcome (complete / blocked) and any commit hashes.
```

### Per-task execution (NOT supported via subagent fan-out)

**Subagents cannot spawn other subagents** (per the Claude Code sub-agents spec). This means a per-phase subagent that runs `tasks-executing` must execute its tasks serially in its own context — it cannot delegate per-task to grandchild subagents.

If you want per-task parallelism in `subagent=full` mode, the **parent** (the workflow skill) must dispatch one subagent per task directly, not nest task-level subagents inside phase-level subagents.

Equivalent prompt for direct per-task dispatch from the parent:

```
Use the Agent tool with subagent_type="general-purpose".

Prompt:
  Read <task-file> and execute Task <ID> only.
  Stay strictly within the task's declared Files and Scope.
  Run the task's Verification command before reporting done.
  Update the task's status in <task-file> on completion.
  Stop and report on any verification failure.
```

### Worktree isolation for parallel phases

When dispatching multiple phase subagents in parallel (subagent=full + independent phases), give each subagent an isolated git worktree by setting `isolation: worktree` in the subagent's frontmatter (or pass it via the Agent tool when supported). This avoids file-write collisions between concurrent subagents and lets the parent merge results after they all return.

If `isolation: worktree` isn't available, fall back to **serial execution** of phases — the file-collision risk outweighs the parallelism gain.

## Parallel Fan-Out Rules

When `subagent=full` and multiple phases or tasks are genuinely independent:

1. **Confirm independence.** A phase is independent if its `Blocked-by` field is `none` and no two phases touch the same file (check the plan's per-phase Files lists).
2. **Cap concurrency.** No more than 3 parallel subagents at once — the plan-file write contention scales badly past that, and tool budget gets noisy.
3. **One subagent per phase.** Never two subagents on the same phase.
4. **Reconcile after return.** When all dispatched subagents return, the parent (the workflow skill) checks the plan file. All `complete`? Run integration verification. Any `blocked`? Read Notes, decide.
5. **Serial fallback.** If during dispatch you discover hidden coupling (two phases that both edit a shared types file), abort the parallel run, mark the colliding phases `blocked`, and route back to **plan-creating** to fix the dependency graph.

## Auto-Mode Behavior

### `auto=no` (default)

After every stage that produces a durable artifact, the model:

1. Updates `state.json` via `advance`.
2. Prints a short stage summary.
3. **Stops** if the next stage is `execute-plan` or `execute-tasks`. Presents the plan + tasks. Waits for user approval.
4. Continues to non-mutating next stages without pausing (e.g. `create-plan` → `create-tasks` doesn't need a pause).

### `auto=yes`

The model:

1. Walks every stage in order without pausing for confirmation.
2. After `create-tasks`, immediately starts `execute-tasks` (or `execute-plan` per the routine).
3. Stops only on:
   - **Blocker** — a stage fails verification or surfaces a missing constraint.
   - **Routine complete** — last stage finished, final report written.
   - **Risk gate** — destructive action (force push, schema drop) — even auto=yes pauses for these. Route through `guardrails`.

The Stop hook (see `references/hooks-config.md`) reinforces auto=yes by re-prompting Claude if it tries to stop mid-routine. Without the hook the model still chains correctly but is more likely to drift toward stopping.

## State File Discipline

`scripts/workflow.sh` is the only writer for `.workflow/state.json`. The model never edits it directly. Instead:

- After each stage: `advance <stage> "<one-line result>"`.
- When a stage produces a durable artifact: `artifact <key> <value>` (e.g. `artifact plan_file plans/2026-04-26-x.md`).
- To pause: just stop calling `advance`. The state file reflects the last completed stage.
- To resume: read state with `status`, decide next stage from `current`, run it, advance.

If two sessions try to advance the same workflow concurrently, the file write race may corrupt JSON. Avoid this by holding workflows in a single session; if a handoff is needed, finish the current stage, summarize, and let the new session pick up via `status`.

## When Subagents Are Wrong

Don't dispatch subagents for:

- **The plan-creating stage.** The plan file is one artifact and one writer.
- **Anything that needs back-and-forth with the user.** Subagents are one-shot.
- **Stages that depend on session-local context not yet committed to disk** (open files, in-progress edits).
- **Trivial stages.** A 30-second `detect-stack` is not worth a subagent round trip.

## Drift Recovery

If during execution you discover the plan disagrees with reality (a phase touches files that were renamed):

1. Mark the affected phase `blocked` in the plan file's Status.
2. In the workflow skill, route back to `create-plan` to amend the plan.
3. Bump the plan's `Last updated`. Add a Notes entry explaining the drift.
4. Resume from the corrected phase.

Never let a subagent silently rewrite the plan to match reality — surface the drift to the user.
