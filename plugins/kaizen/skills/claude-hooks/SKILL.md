---
name: claude-hooks
description: Use when the user asks to "create a hook", "wire a hook", "add a Stop/SessionStart/PreToolUse/SubagentStop/PreCompact hook", configure settings.json hooks, block tool calls, inject session context, survive compaction, auto-advance subagents, or troubleshoot Claude Code hook firing. Covers all 9 lifecycle events with input/output JSON schemas, matcher syntax, exit-code semantics, and copy-paste wiring recipes.
---

# Claude Code Hooks

Hooks are shell commands the Claude Code harness runs at lifecycle events. They receive a JSON event payload on stdin and influence Claude's behavior via stdout JSON or exit codes. Hooks run **outside** the model — they are deterministic harness automation, not prompts.

## When hooks are the right answer

| Need | Hook |
|---|---|
| Inject project context every session / prompt | `SessionStart`, `UserPromptSubmit` |
| Block / gate / log tool calls | `PreToolUse`, `PostToolUse` |
| Force Claude to keep working past a stop | `Stop` (with `decision:"block"`) |
| Auto-advance a workflow when a subagent finishes | `SubagentStop` |
| Save state before compaction wipes context | `PreCompact` |
| Notify on long-running waits | `Notification` |
| Cleanup on exit | `SessionEnd` |

If a behavior must happen **deterministically** every time (not "if Claude remembers to"), it's a hook. Memory and CLAUDE.md cannot fulfill "from now on whenever X" — the harness must.

## The 9 lifecycle events

1. **SessionStart** — session opens (sources: `startup`, `resume`, `clear`, `compact`)
2. **UserPromptSubmit** — user sent a prompt; fires before model sees it
3. **PreToolUse** — model is about to call a tool; can block
4. **PostToolUse** — tool returned; can append context
5. **Notification** — harness wants to alert user (idle, waiting input)
6. **Stop** — model wants to end its turn; can force continuation
7. **SubagentStop** — a dispatched subagent finished
8. **PreCompact** — context window is about to be auto-compacted
9. **SessionEnd** — session is closing

For full input/output schemas of each event see [references/event-schemas.md](references/event-schemas.md).

## Wiring (settings.json)

All hook config lives under `hooks.<EventName>` as an array of matcher blocks:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "bash $HOME/.claude/scripts/inject-context.sh session" }
        ]
      }
    ]
  }
}
```

- `matcher`: `"*"` for all, or a tool-name regex for `PreToolUse`/`PostToolUse` (e.g. `"Bash"`, `"Edit|Write"`).
- `command`: any shell. Receives event JSON on stdin. `$CLAUDE_PROJECT_DIR` is set for plugin-aware hooks.
- Multiple matcher blocks per event are allowed — all matching ones run.

For copy-paste recipes (context injection, tool-call gating, secret scanning, auto-advance) see [references/wiring-recipes.md](references/wiring-recipes.md).

## How hooks influence Claude

Two channels: **exit code** and **stdout JSON**. Stdout JSON is more expressive — prefer it.

### Exit-code semantics

| Exit | Meaning |
|---|---|
| `0` | Success. stderr discarded. |
| `2` | Block / deny. stderr fed back to Claude as the reason. Works for `PreToolUse`, `Stop`, `SubagentStop`, `UserPromptSubmit`. |
| other | Soft error. stderr shown to user. Claude continues. |

### Stdout JSON

The universal envelope is `{"hookSpecificOutput": { "hookEventName": "<Event>", ... }}`. Common fields:

- `decision`: `"block"` (event-specific behavior) or omitted.
- `reason`: human/agent-readable string explaining the decision.
- `additionalContext`: string injected into Claude's context (only honored on `SessionStart`, `UserPromptSubmit`, `PostToolUse`).
- `systemMessage`: short string surfaced as a transient system note.
- `permissionDecision`: `"allow" | "deny" | "ask"` — for `PreToolUse` to override the permission prompt.
- `permissionDecisionReason`: explanation for the decision above.
- `suppressOutput`: `true` hides hook stdout from the user transcript.

Example — force Claude to keep working when a workflow is mid-routine:

```json
{ "decision": "block", "reason": "Workflow auto=yes is active; advance to next stage." }
```

Example — gate a Bash command:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "rm -rf on /etc is forbidden."
  }
}
```

## The auto-advance pattern (worked example)

The local `workflow.sh` orchestrator uses three hooks to drive multi-stage routines without user intervention:

1. **Stop hook** — if a workflow has `auto=yes`, return `{"decision":"block"}` so Claude keeps working.
2. **SubagentStop hook** — when a dispatched subagent completes, advance the workflow's `current` stage and emit `systemMessage` telling Claude what to run next.
3. **PreCompact hook** — write a state snapshot to disk so the next `SessionStart` (with `source=compact`) can re-inject the workflow recap.

Full code walkthrough in [references/auto-advance-pattern.md](references/auto-advance-pattern.md).

## Debugging hooks

- **It didn't fire**: check `claude --debug` output for `[hook] firing X` lines, verify settings.json path, confirm matcher matches.
- **JSON ignored**: stdout must be a single JSON object, no leading text. Wrap shell echo in `python3 -c 'import json; print(json.dumps(...))'`.
- **Block didn't block**: `decision:"block"` only works on events that support it (Stop, PreToolUse, UserPromptSubmit, SubagentStop). For others, use exit code 2.
- **Test in isolation**: `echo '{"session_id":"x","cwd":"."}' | bash your-hook.sh` and inspect output.

## Hard rules

- **Never use stdin without `set -uo pipefail` discipline.** A failing collector with `set -e` aborts the hook silently.
- **Hooks block the session.** Keep them under ~500ms. Background long work with `&` and a logfile.
- **Don't write secrets to stdout.** Everything in `additionalContext` is fed into the model.
- **Subagents can't spawn subagents.** A `SubagentStop` hook is your only signal that a subagent finished — don't try to nest.

## Project context

This system already wires four hooks via `~/.claude/settings.json`:

- `SessionStart` → `~/.claude/scripts/inject-context.sh session` (injects active workflow / plans / git state)
- `Stop` → `~/.claude/scripts/ops/workflow.sh stop-hook` (auto-continues `auto=yes` workflows)
- `SubagentStop` → `~/.claude/scripts/ops/workflow.sh subagent-stop` (advances workflow on subagent completion)
- `PreCompact` → `~/.claude/scripts/ops/workflow.sh pre-compact` (writes recap snapshot for post-compact recovery)

The `inject-context.sh` script reads the SessionStart `source` field and emits a richer recap when `source=compact` (recovery after auto-compaction).
