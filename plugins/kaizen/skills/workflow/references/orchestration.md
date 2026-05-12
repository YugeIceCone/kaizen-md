# Orchestration — subagent dispatch, parallel fanout, hooks

Hand-written reference. Not generated. Complements the orchestration loop overview in `SKILL.md` with concrete dispatch templates, parallelism rules, and hook recipes for `settings.json`.

## Subagent dispatch modes

### `subagent=no` (default)

Pure single-session run. The current Claude instance runs every stage in order. Plan files + artifacts are written directly. No `Agent` tool calls dispatched on the workflow's behalf (the agent may still invoke them for its own purposes).

When to use: small features, debugging, anything where context-continuity beats parallelism. Default.

### `subagent=yes` — read-only delegation

Read-only stages (explore / research / audit / analyze / review) dispatch to subagents. Planning + writes stay in the current session. Use this when context budget matters but you want full control over edits.

Dispatch template:

```python
Agent(
  description="<stage> — <routine>",
  subagent_type="general-purpose",
  prompt="Run the <stage> stage of the <routine> routine for: <prompt>.\\n\\n"
         "Self-contained — explore + report findings in under <N> words. "
         "Do NOT edit any code; this is a read-only stage."
)
```

Use `Explore` subagent for codebase mapping; `general-purpose` for everything else. Subagents return summaries; the parent records them as artifacts via `workflow.sh artifact <stage>_findings <path>`.

### `subagent=full` — execution delegation

Execution stages (execute-tasks / execute-plan) dispatch one subagent per phase or task batch, parallelizing where the plan declares no inter-phase dependencies. Requires the plan to be **agent-reusable** (see `kaizen:writing-plans` skill).

Dispatch template for parallel phases:

```python
# Send ONE message with multiple Agent calls — runs in parallel
Agent(description="phase 1", prompt="Execute phase 1 of plan X...")
Agent(description="phase 2", prompt="Execute phase 2 of plan X...")
Agent(description="phase 3", prompt="Execute phase 3 of plan X...")
```

Each subagent gets the full plan path + its phase number + the resume protocol. Parent monitors via `workflow.sh status` and `TaskList`.

**Parallel-fanout rule:** only fan out phases that are declared independent in the plan's `## Phase independence` section. Phases with shared file targets must serialize.

## Stage → skill map (full)

Each stage routes to a single skill. Subagent flag may further wrap the invocation.

| Stage | Skill | Subagent type (when subagent=yes) |
|---|---|---|
| explore | `kaizen:explore` | `Explore` |
| detect-stack | `kaizen:detect-stack` | `general-purpose` |
| research | `kaizen:research` | `general-purpose` |
| analyze | built-in `analyze` | `general-purpose` |
| audit | `kaizen:audit` | `general-purpose` |
| debug | `kaizen:systematic-debugging` | (not dispatched) |
| fix | built-in `fix` | (not dispatched — single session) |
| create-plan | `kaizen:writing-plans` | (not dispatched — local writes) |
| create-tasks | built-in `create-tasks` | (not dispatched) |
| execute-tasks | built-in `execute-tasks` | one per task batch (subagent=full) |
| execute-plan | `kaizen:executing-plans` | one per phase (subagent=full) |
| review | `kaizen:review` | `general-purpose` |
| validate | built-in `validate` | (not dispatched — full session) |
| simplify | bundled `/simplify` | n/a (atomic) |
| batch-fanout | bundled `/batch` | n/a (atomic) |
| report | built-in `report` | (not dispatched) |

## Auto-mode behavior

`auto=yes` chains every stage end-to-end without pausing. The implementation has two parts:

1. **Workflow.sh** does NOT pause between stages — `advance` is called automatically.
2. **Stop hook** (configured in user settings.json) re-prompts Claude if the model tries to stop mid-routine.

Sample Stop hook (project-agnostic):

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash $​HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/workflow.sh stop-hook"
          }
        ]
      }
    ]
  }
}
```

The `stop-hook` subcommand reads Claude Code Stop event JSON from stdin and emits `decision: block` when `state.auto_mode=yes` and the workflow is mid-flight.

## SessionStart hook (resume)

Surface active-workflow context on every session start:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash $​HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/workflow.sh status 2>/dev/null || true"
          }
        ]
      }
    ]
  }
}
```

`workflow.sh status` prints a one-line summary if a workflow is mid-flight; silent if not. Injected as additionalContext.

## PreToolUse hook (guardrail)

Block destructive bash during a workflow if `auto=yes`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash $​HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/workflow.sh pre-tool-guard"
          }
        ]
      }
    ]
  }
}
```

Refuse `git push --force`, `rm -rf`, `git clean -fd`, etc. unless an explicit override env is set. Audit-trail goes to `state.json.tool_blocks[]`.

## PreCompact hook (state preservation)

Before context compaction, persist the workflow state summary so the post-compact session can resume:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash $​HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/workflow.sh pre-compact"
          }
        ]
      }
    ]
  }
}
```

Writes `.kaizen/workflow/snapshot.md` — a human-readable freeze-frame of the active routine + stage + last 3 completed stages.

## SubagentStop hook (auto-advance)

When a dispatched subagent completes, auto-advance its mapped stage:

```json
{
  "hooks": {
    "SubagentStop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash $​HOME/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/workflow.sh subagent-stop"
          }
        ]
      }
    ]
  }
}
```

Reads SubagentStop event JSON, looks up agent_id in `state.subagents`, and calls `advance` if `stop_reason=completed`.

## End-state guarantees

For every routine, the orchestration loop ensures:

- **audit / harden / build-feature / refactor / migrate** — durable plan at `plans/<date>-<topic>.md` with Goal, Current State, Invariants, per-phase Status, Verification, Resume Protocol. `auto=yes` also executes the plan and writes a final report.
- **fix-bug** — verified fix landed + regression test + one-paragraph report.
- **batch-migrate** — N PR URLs recorded in `state.artifacts.prs`; report summarizes landed-vs-deferred.
- **any routine** — when blocked: clear blocker note in state.json + user-facing explanation paragraph.

If a stage fails verification, the workflow STOPS — never silently retries. The agent surfaces the failure with full details + asks the user.
