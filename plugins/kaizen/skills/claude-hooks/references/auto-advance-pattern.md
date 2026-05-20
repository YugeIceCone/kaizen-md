# Auto-Advance Pattern (Workflow Orchestration)

A worked example: how `~/.claude/scripts/ops/workflow.sh` chains 4 hooks to drive a multi-stage routine without user intervention. This is the canonical "use hooks to give Claude a state machine" pattern.

## State

`.kaizen/workflow/state.json` holds a single workflow's progress:

```json
{
  "routine": "audit",
  "stages": ["explore", "detect-stack", "audit", "report"],
  "current": 1,
  "completed": [{ "stage": "explore", "msg": "...", "at": "..." }],
  "subagents": { "agent-001": "explore" },
  "artifacts": { "plan_file": "plans/2026-04-26-audit.md" },
  "auto_mode": "yes",
  "subagent_mode": "full"
}
```

`workflow.sh` is the only writer. Hooks call its subcommands.

## Lifecycle

```
T0  user: /workflow do an audit auto=yes
T1  Claude runs:  workflow.sh init audit "do an audit" auto=yes
T2  Claude runs first stage (explore) — possibly via subagent dispatch
T3  Claude calls: workflow.sh dispatch agent-001 explore
T4  ... subagent runs ...
T5  subagent finishes  →  SubagentStop hook fires
T6    workflow.sh subagent-stop reads agent-001, sees "explore",
      auto-advances current=1→2, emits systemMessage
T7  Claude reads systemMessage, runs detect-stack
T8  Claude tries to stop  →  Stop hook fires
T9    workflow.sh stop-hook sees auto=yes + not-last-stage,
      emits {"decision":"block","reason":"advance to audit"}
T10 Claude continues to "audit" stage
...
T13 last stage done  →  Stop hook sees current >= len(stages),
      emits {} — Claude actually stops.
```

## The four hooks

### 1. SessionStart — context recap

```bash
SessionStart → bash ~/.claude/scripts/inject-context.sh session
```

Reads `.kaizen/workflow/state.json`, prints a Markdown recap of routine + next stage + artifacts. On `source=compact`, reads `.kaizen/workflow/snapshot.md` (richer recovery payload).

### 2. Stop — auto-continuation

```bash
Stop → bash ~/.claude/scripts/ops/workflow.sh stop-hook
```

Pseudocode:
```python
state = load(".kaizen/workflow/state.json")
if not state: print("{}"); exit(0)
if state["auto_mode"] != "yes": print("{}"); exit(0)
if state["current"] >= len(state["stages"]): print("{}"); exit(0)  # done
next_stage = state["stages"][state["current"]]
print(json.dumps({
    "decision": "block",
    "reason": f"Workflow auto=yes is mid-routine. Run the '{next_stage}' stage next, then call: workflow.sh advance {next_stage} \"<result>\""
}))
```

### 3. SubagentStop — auto-advance on subagent completion

```bash
SubagentStop → bash ~/.claude/scripts/ops/workflow.sh subagent-stop
```

Pseudocode:
```python
event = json.load(sys.stdin)
agent_id = event.get("agent_id")
state = load(".kaizen/workflow/state.json")
stage = state.get("subagents", {}).get(agent_id)
if not stage:
    print("{}"); exit(0)  # not our subagent
if event.get("stop_reason") == "completed":
    advance(state, stage, "subagent done")
    next_stage = state["stages"][state["current"]]
    print(json.dumps({
        "systemMessage": f"Workflow auto-advanced: {stage} -> {next_stage}. Run '{next_stage}' next."
    }))
else:
    print(json.dumps({
        "systemMessage": f"Subagent {agent_id} ended with {event['stop_reason']} during {stage}. Investigate before advancing."
    }))
```

### 4. PreCompact — survive context loss

```bash
PreCompact → bash ~/.claude/scripts/ops/workflow.sh pre-compact
```

Writes `.kaizen/workflow/snapshot.md` with the full state recap, completed history, last 3 artifact paths. The next SessionStart (with `source=compact`) loads this back into context.

## Why this works

- **State lives on disk** (`state.json`) — survives session restart, compaction, subagent fan-out.
- **Hooks are the only auto-trigger** — Claude can't "forget" to advance because the harness fires Stop unconditionally.
- **Subagents can't nest hooks** — the parent's SubagentStop is the single point of truth for "stage N done".
- **`auto_mode` gates the Stop block** — workflows that explicitly opted out of auto-mode get a clean stop point for human approval.

## Failure modes & guards

- **Infinite Stop loop.** Guard with `stop_hook_active` field on the event. If true, the hook already blocked once this turn — let Claude stop. Modern fix: cap recursion by checking `current` against `len(stages)`.
- **Two sessions advancing the same workflow.** File-write race corrupts JSON. The state machine assumes one session per workflow at a time. Holding work in a single session is the discipline.
- **Subagent that doesn't get tracked via `dispatch`.** Its SubagentStop fires with an unknown `agent_id` → hook prints `{}` and Claude isn't auto-advanced. Always `dispatch <agent_id> <stage>` immediately before calling Agent.

## Ports to other use cases

This same pattern (state.json + Stop + SubagentStop + PreCompact) generalizes to:
- **Long-running test/build chains** — Stop blocks until `make ci` returns 0
- **Multi-PR refactors** — state tracks PR list, SubagentStop advances after each PR's reviewer subagent finishes
- **Eval loops** — Stop blocks until eval score crosses threshold

The key insight: **hooks turn the harness into a deterministic driver around the model**, so multi-step workflows don't depend on the model remembering its place.
