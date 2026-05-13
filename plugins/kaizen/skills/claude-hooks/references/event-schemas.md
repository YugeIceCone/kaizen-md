# Hook Event Schemas

All events receive a JSON payload on stdin. Common fields on every event:

```json
{
  "session_id": "string",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/working/dir",
  "hook_event_name": "<EventName>"
}
```

Event-specific fields below.

---

## SessionStart

Fires when a session begins or resumes.

**Input extras:**
```json
{ "source": "startup | resume | clear | compact" }
```

- `startup`: fresh `claude` invocation
- `resume`: `--resume` / `--continue` / `/resume`
- `clear`: `/clear` was run
- `compact`: auto- or manual-compaction just happened (use to re-inject pre-compaction state)

**Output:** inject context.
```json
{ "hookSpecificOutput": { "hookEventName": "SessionStart", "additionalContext": "string" } }
```

Or simple stdout text — Claude Code will inject it as additional context too.

---

## UserPromptSubmit

Fires after the user submits a prompt, before Claude sees it.

**Input extras:**
```json
{ "prompt": "the user's text" }
```

**Output options:**
- Inject context: `{ "hookSpecificOutput": { "hookEventName": "UserPromptSubmit", "additionalContext": "..." } }`
- Block prompt: `{ "decision": "block", "reason": "shown to user, not Claude" }` or exit 2 with stderr (which IS shown to Claude).
- Validate: silently transform / scan / reject.

Use case: secret scanning, project-context injection, prompt enrichment.

---

## PreToolUse

Fires before any tool call, after the matcher matches `tool_name`.

**Input extras:**
```json
{ "tool_name": "Bash", "tool_input": { ... tool args ... } }
```

**Matcher:** regex against `tool_name`. Examples: `"Bash"`, `"Edit|Write|MultiEdit"`, `"mcp__.*"`, `"*"` for all.

**Output (the modern way):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow | deny | ask",
    "permissionDecisionReason": "shown to Claude on deny, to user on ask"
  }
}
```

- `allow`: bypass the user's permission prompt — auto-approve.
- `deny`: block the tool call. `permissionDecisionReason` is fed back to Claude.
- `ask`: force the user prompt even if the tool would normally auto-allow.

**Legacy (still works):** exit 2 with stderr to deny.

---

## PostToolUse

Fires after a tool call returns successfully.

**Input extras:**
```json
{ "tool_name": "...", "tool_input": {...}, "tool_response": {...} }
```

**Output:** inject context for Claude to see alongside the tool result.
```json
{ "hookSpecificOutput": { "hookEventName": "PostToolUse", "additionalContext": "..." } }
```

Use case: auto-format-on-save, log tool usage, append diagnostic notes after edits.

---

## Notification

Fires when the harness wants to alert the user (e.g., waiting on input).

**Input extras:**
```json
{ "message": "string" }
```

**Output:** typically none. Side-effect-only (system notification, log).

---

## Stop

Fires when Claude wants to end its turn.

**Input extras:**
```json
{ "stop_hook_active": true | false }
```

(`true` if a previous Stop hook already blocked once this turn — guards against infinite loops.)

**Output:**
```json
{ "decision": "block", "reason": "Claude reads this and continues working" }
```

If `decision="block"`, the `reason` is fed to Claude as instruction to keep going. Use for forcing test-on-stop, lint-on-stop, or auto-advance of multi-stage workflows.

---

## SubagentStop

Fires when a dispatched subagent (via Task / Agent tool) finishes.

**Input extras:**
```json
{
  "agent_id": "string or null",
  "stop_reason": "completed | cancelled | failed | error",
  "stop_hook_active": false
}
```

**Output:**
- Auto-advance state (set `systemMessage` to inform parent Claude what happened).
- Block to force re-dispatch on failure (rarely useful).

```json
{
  "systemMessage": "Subagent X completed phase 2; advance to phase 3.",
  "hookSpecificOutput": { "hookEventName": "SubagentStop", "additionalContext": "..." }
}
```

---

## PreCompact

Fires just before context auto-compaction. Last chance to persist transient state.

**Input extras:**
```json
{ "trigger": "auto | manual", "custom_instructions": "string or null" }
```

**Output:** none required. Side-effect: write a state snapshot to disk; pair with `SessionStart` (`source=compact`) to restore.

---

## SessionEnd

Fires when the session is closing.

**Input extras:**
```json
{ "reason": "exit | logout | prompt_input_exit | other" }
```

**Output:** none. Side-effect-only — final cleanup, state persistence, telemetry.

---

## Decision matrix (which output channel to use)

| Event | Block? | Inject context? | Field |
|---|---|---|---|
| SessionStart | no | yes | `additionalContext` |
| UserPromptSubmit | yes (`decision:"block"` or exit 2) | yes | `additionalContext` |
| PreToolUse | yes | no | `permissionDecision` |
| PostToolUse | no | yes | `additionalContext` |
| Notification | no | no | — |
| Stop | yes | no | `decision:"block"`, `reason` |
| SubagentStop | yes | yes | `systemMessage`, `additionalContext` |
| PreCompact | no | no | — (write snapshot) |
| SessionEnd | no | no | — |
