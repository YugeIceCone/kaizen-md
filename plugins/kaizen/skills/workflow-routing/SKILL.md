---
name: workflow-routing
description: Run a curated structured workflow that chains research / explore / analyze / plan / task-create / execute / review stages and produces an agent-reusable plan with tasks. Use when the user invokes /workflow, asks to "run a structured workflow", "do a full audit", "build feature end-to-end", "fix bug end-to-end", "refactor with a plan", or when a multi-stage routine needs orchestration with subagent + auto-mode controls.
metadata:
  version: "2.0"
---

# Workflow Routing

Run a curated, structured routine that walks a request through the right sequence of skills and ends with a durable, agent-reusable plan plus task list (and optionally executes it). The skill is the orchestration brain; `scripts/workflow.sh` is the persistent state machine; `references/routines.md` defines the stage sequences.

This skill replaces the older one-shot routing model. It is invoked by the `/workflow` slash command (`~/.claude/commands/workflow.md`) but also activates whenever the user asks for an end-to-end run of a known routine.

## Routines

Two ways to source the stage sequence: **hardcoded** (verb-detected from the prompt) and **schema-driven** (declarative yaml, opt-in via `schema=<name>`, added v1.14.0).

### Hardcoded routines (default)

The script maps the user's prompt to one of six curated routines (full sequences in `references/routines.md`):

- **audit** — `explore → detect-stack → research → audit → analyze → review → create-plan → create-tasks` (ends with a plan; auto=yes also reports findings)
- **build-feature** — `explore → detect-stack → research → analyze → create-plan → create-tasks → execute-tasks → review → report`
- **fix-bug** — `debug → analyze → fix → review → validate → report`
- **refactor** — `explore → analyze → create-plan → create-tasks → execute-tasks → review → validate`
- **migrate** — `research → explore → analyze → create-plan → create-tasks → execute-tasks → review → validate`
- **harden** — `explore → audit → analyze → create-plan → create-tasks → execute-tasks → review → validate`

The user may pin a starting stage with `skill=NAME` to skip earlier stages. Any unknown verb defaults to `build-feature`.

### Schema-driven routines (v1.14.0+)

Pass `schema=<name>` and the stage sequence comes from a declarative yaml file. Three built-ins ship:

- **minimalist** — `specs → tasks` (low-ceremony; Given/When/Then or EARS acceptance)
- **kaizen-default** — `explore → research → analyze → plan → tasks → execute → review → validate` (mirrors the hardcoded default)
- **spec-driven** — `analyze → design → (decisions, tasks) → implement → validate → reflect → handoff` (EARS requirements + Decision Records, adapted from GitHub's awesome-copilot spec-driven-workflow-v1)

Schemas resolve in this order (first hit wins):
1. `<repo>/.workflow/schemas/<name>/schema.yaml` (project-versioned)
2. `~/.claude/kaizen-schemas/<name>/schema.yaml` (user-wide)
3. `<plugin>/schemas/<name>/schema.yaml` (built-in)

Inspect schemas with `/kaizen:schema list|show|validate|stages|artifact`. The state machine treats schema-driven and hardcoded routines identically once initialized — `routine` is `schema:<name>` instead of `audit`/`build-feature`/etc., and `schema_name` is recorded in state.json. All `advance`, `dispatch`, `status`, `subagent-stop`, `pre-compact`, `post-compact` logic is unchanged.

## When To Use

Trigger this skill when:

- the `/workflow` command was invoked (the command file points here)
- the user asks for an end-to-end audit, build, fix, refactor, migration, or hardening pass
- a multi-stage routine needs sequencing with subagent + auto-mode controls
- a `.workflow/state.json` file already exists in the project and needs to advance

If only a single skill is needed (e.g. "just create a plan"), redirect to that skill instead.

## Inputs

From `/workflow` arguments (parsed by the script):

- **prompt** — what the user wants done
- **skill=NAME** — optional starting stage (else auto-detect)
- **subagent=no|yes|full** — delegation mode (default `no`)
- **auto=no|yes** — autonomy (default `no`)
- **schema=NAME** — optional (v1.14.0+) source stages from a declarative schema instead of a hardcoded routine. See "Schema-driven routines" above.

Also reads `.workflow/state.json` if present (for resume).

## Orchestration Loop

1. **Initialize.** Run the init script (the `/workflow` command does this). The script writes `.workflow/state.json` and prints the routine, the stages, and the first stage to run.
2. **Read state.** Load `.workflow/state.json` to know the routine, current stage index, completed stages, subagent mode, auto mode, and any artifacts already produced.
3. **Run the current stage.** Invoke the matching skill (e.g. `explore`, `create-plan`). Honor the `subagent` mode per `references/orchestration.md`:
    - `no` — run the stage in this session
    - `yes` — dispatch a subagent for read-only stages (explore, research, audit, analyze, review)
    - `full` — dispatch subagents for as many stages as possible, in parallel where independent
4. **Capture artifacts.** When a stage produces a durable artifact (plan file, task file, audit report), record it:
    ```bash
    bash <script> artifact plan_file plans/2026-04-26-x.md
    ```
5. **Advance.** When the stage completes, run:
    ```bash
    bash <script> advance <stage> "<one-line result summary>"
    ```
   The script updates state and prints the next stage.
6. **Pause point** (when `auto=no` and the next stage is an execution stage):
    - After `create-tasks`, stop and present the plan + tasks to the user. Ask for approval before continuing to `execute-tasks` / `execute-plan`.
7. **Auto-continuation** (when `auto=yes`):
    - Do not pause. Walk through all stages until the routine completes or a stage is blocked.
    - The `Stop` hook (see `references/hooks-config.md`) reinforces this by re-prompting Claude if the model tries to stop mid-routine.
8. **Final report.** After the last stage, summarize what was produced (plan path, tasks, diffs, verification results) and clear or archive the state file.

## Stage → Skill Mapping

Each stage routes to a single skill:

| Stage | Skill |
|---|---|
| explore | `codebase-exploring` (skill: `explore`) |
| detect-stack | `stack-detecting` (skill: `detect-stack`) |
| research | `topic-researching` (skill: `research`) |
| analyze | `change-analyzing` (skill: `analyze`) |
| audit | `proactive-auditing` (skill: `audit`) |
| debug | `debugging-failures` (skill: `debug`) |
| create-plan | `plan-creating` (skill: `create-plan`) |
| create-tasks | `tasks-creating` (skill: `create-tasks`) |
| execute-plan | `plan-executing` (skill: `execute-plan`) |
| execute-tasks | `tasks-executing` (skill: `execute-tasks`) |
| fix | `bug-fixing` (skill: `fix`) |
| review | `change-reviewing` (skill: `review`) |
| validate | `plan-validating` (skill: `validate`) |
| report | `report-generating` (skill: `report`) |

## Subagent + Auto Modes

- **`subagent=no`** — pure single-session run, no delegation.
- **`subagent=yes`** — dispatch read-only stages (explore, research, audit, analyze, review) to subagents using the `Explore` and `general-purpose` built-ins. Keeps planning + writes local. Use when context budget matters but you want full control over edits.
- **`subagent=full`** — also dispatch execution stages (one subagent per phase or task batch), parallelizing where the plan declares no inter-phase dependencies. Requires the plan to be agent-reusable (see `create-plan` skill).
- **`auto=no`** — pause for user approval after `create-tasks` (plan ready) and after any stage marked `blocked`.
- **`auto=yes`** — chain end-to-end. Pair with the Stop-hook config in `references/hooks-config.md` so the model is nudged to continue after each turn.

Detailed dispatch templates and parallel-fanout rules: `references/orchestration.md`.

## End-State Guarantees

For every routine, the workflow ends with at least one of:

- **Audit / harden / build-feature / refactor / migrate** — a durable plan file at `plans/<date>-<topic>.md` containing Goal, Current State, Invariants, per-phase Status, Verification Commands, and a Resume Protocol (see `create-plan` skill). When `auto=yes`, the plan is also executed and a final report is appended.
- **Fix-bug** — a verified fix landed in code, with a regression test, plus a one-paragraph report.
- **Any routine** — when blocked, a clear blocker note in the state file and a one-paragraph user-facing explanation.

## Hooks Integration

The `scripts/workflow.sh stop-hook` subcommand reads Claude Code Stop event JSON from stdin and emits a `decision: block` response when `auto=yes` and the workflow is mid-flight. Wire it in user `settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": "bash $HOME/.claude/skills/workflow/scripts/workflow.sh stop-hook"}
        ]
      }
    ]
  }
}
```

Full hook recipes (PreToolUse guard, SessionStart resume, plus risks) in `references/hooks-config.md`.

## When To Redirect

- single-skill request → use that skill directly, skip the workflow
- the user wants to inspect the current workflow → `bash <script> status`
- a workflow is stuck → mark the stage `blocked` in state, surface the cause, ask the user
- the user wants to drop the current workflow → `bash <script> reset`

## Companion Skills

- **`supervisor`** — picks among workflow stages when no curated routine fits
- **`plan-creating`** / **`plan-executing`** — produce/run the agent-reusable plan that the routine targets
- **`tasks-creating`** / **`tasks-executing`** — produce/run the task batch
- **`dispatching-parallel-agents`** — used when `subagent=full` parallelizes phases
- **`guardrails`** — gate the transition to `execute-tasks` when `auto=yes`
- **`memory-managing`** — persist context if the routine needs to survive `/compact`

## Rules

- One stage at a time, in the routine order — do not skip ahead.
- Update state.json via `advance` after every completed stage.
- Honor `subagent=` and `auto=` modes; do not silently override them.
- Stop and report on any stage failure; never silently retry.
- The end of every routine produces a durable artifact (plan, fix + test, or blocker note).
- Avoid Markdown tables in artifacts the routine produces (the routine's own SKILL.md may use them).

## Additional Resources

- **`references/routines.md`** — full routine sequences, stage-by-stage prompts, anti-patterns
- **`references/orchestration.md`** — subagent dispatch templates, parallel-fanout rules, auto-mode behavior
- **`references/hooks-config.md`** — Stop / SessionStart / PreToolUse hook recipes for `settings.json`
- **`scripts/workflow.sh`** — state machine + hook handler (subcommands: init / next / advance / artifact / status / reset / stop-hook)
