# Trace + Hook + Tool surface API

The kaizen plugin sits inside Claude Code's hook + tool surface and
emits its own trace events. This reference catalogs the contracts —
what to call, what data flows where, and which env knobs disable
each layer.

---

## 1. Trace surface (kaizen-internal)

The trace surface is **plugin-owned** — events land in
`~/.claude/.kaizen/trace/events.jsonl` (override via `KAIZEN_TRACE_DIR`).

### `trace.py` — append-only event log

```python
from skills.workflow.scripts import trace

trace.append_event({
    "ts":  trace._now_iso(),     # ISO 8601 UTC
    "src": "hook",               # hook | agent | llm | tool | user | cc | plugin | workflow
    "evt": "PreToolUse-Bash",    # arbitrary string
    "tool": "Bash",              # optional — tool name
    "sid": "<session-uuid>",     # optional — Claude Code session-id
    "ms": 156,                   # optional — duration
    "data": {...},               # optional — free-form payload
})
```

**File:** `skills/workflow/scripts/trace.py`
**Disable:** `KAIZEN_TRACE_DISABLE=1` (silently no-ops)
**Rotation:** auto via `_max_mb()` + `_retention_days()`

### `_dxm_emit.py` — per-session event mirror

Distinct from `trace.py`. dxm captures the **live session-mirror**
(per-session JSONL at `~/.claude/.kaizen/dxm/events-<sid>.jsonl`).

```python
from skills.workflow.scripts import _dxm_emit

_dxm_emit.emit_event(
    "handoff.verify.complete",            # evt_type
    tool_name="kaizen-handoff",           # optional
    payload={"verdict": "clean", ...},    # optional
    session_id="<sid>",                   # optional — auto-discovers via cwd
)

# Convenience for handler-completion events:
_dxm_emit.emit_subcommand_complete(
    "handoff", "verify", {"verdict": "clean"})
# → emits "handoff.verify.complete" with tool_name="kaizen-handoff"
```

**File:** `skills/workflow/scripts/_dxm_emit.py`
**Disable:** `KAIZEN_DXM_DISABLE=1`
**Auto-discover sid:** when `session_id` omitted, walks
`Path.cwd() → cwd-slug → ~/.claude/projects/<slug>/<latest>.jsonl`

### Iron-law contract

Every hook script under `hooks/claude/` MUST trace its firing via
ONE of:

- `bash $PLUGIN_ROOT/hooks/claude/_trace.sh <event-name>` (shell-side)
- `python3 -m trace event --src hook --evt <name>` (Python-side)
- Direct `trace.append_event(...)` import (in a helper the hook calls)
- Direct `_dxm_emit.emit_event(...)` (treated as trace by iron-laws)

Checked by `iron-laws::every-hook-script-traces-its-firing` — the
check follows `python3 .../X.py` invocations into helper scripts
so consolidated hot-path hooks still pass.

---

## 2. Hook surface (Claude Code lifecycle)

Claude Code fires 9 lifecycle events. The plugin's `hooks/hooks.json`
wires bash scripts to each. **All 9 are wired** as of v1.41+.

### Lifecycle event reference

| Event | Fires when | Stdin payload (typical) | Can return |
|---|---|---|---|
| `SessionStart` | Session boot (also `source: compact` after /compact) | `{session_id, cwd, source}` | `{hookSpecificOutput: {additionalContext: "..."}}` |
| `UserPromptSubmit` | User submits a prompt | `{session_id, prompt, cwd}` | `{hookSpecificOutput: {additionalContext: "..."}}` |
| `PreToolUse` | Before any tool call | `{session_id, tool_name, tool_input, tool_use_id}` | `{permissionDecision: "ask\|allow\|deny", reason}` |
| `PostToolUse` | After any tool call | `{session_id, tool_name, tool_use_id, tool_response, duration_ms}` | `{hookSpecificOutput: {additionalContext: "..."}}` |
| `Stop` | Assistant finishes a turn | `{session_id, last_assistant_message, transcript_path}` | `{decision: "block", reason: "..."}` |
| `SubagentStop` | An Agent tool subagent returns | `{session_id, subagent_type, status, description}` | `{}` (additive only) |
| `PreCompact` | Before `/compact` summarizes | `{session_id}` (minimal) | `{systemMessage: "..."}` (informational) |
| `SessionEnd` | Session close / `/clear` | `{session_id, transcript_path}` | `{}` (additive only) |
| `Notification` | CC requests user attention | `{session_id, message}` | `{hookSpecificOutput: {additionalContext: "..."}}` |

### Output decision shapes

```jsonc
// 1. Silent (no inject, no block)
{}

// 2. Inject context (next turn sees it)
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "block of text the agent sees"
  }
}

// 3. Block — agent CANNOT stop (Stop hook only)
{
  "decision": "block",
  "reason": "imperative text — fed as next-turn prompt"
}

// 4. Permission decision — gate tool calls (PreToolUse only)
{
  "permissionDecision": "ask",          // ask | allow | deny
  "reason": "user-facing explanation"
}

// 5. SystemMessage — surface a one-time advisory
{
  "systemMessage": "⚠ kaizen: ..."
}
```

### Iron-law contracts per hook

Every hook must satisfy:

- **bypass-knob** — read `KAIZEN_<FEATURE>_DISABLE` early; exit 0 if set
- **traces-its-firing** — see Trace surface above
- **emits valid JSON** to stdout (or empty for no-op)
- **plugin.json permission entry** — `Bash(bash ${CLAUDE_PLUGIN_ROOT}/hooks/claude/<name>.sh:*)`
- **never blocks the host** — wrap python3 calls in `|| true`, redirect stderr

### Hook frequency tiers (perf-relevant)

| Tier | Hooks | Fire rate | Optimization priority |
|---|---|---|---|
| **Hot** | PreToolUse / PostToolUse | every tool call (~1000/session) | minimize python3 spawns (use consolidated helpers) |
| **Warm** | UserPromptSubmit / Stop | every assistant turn (~50/session) | one python3 spawn OK |
| **Cold** | SessionStart / SessionEnd / PreCompact | once per session | comfort over speed |
| **Rare** | SubagentStop / Notification | sparse | comfort over speed |

The consolidated hot-path hooks (pretooluse-trace.sh,
posttooluse-trace.sh, userprompt-inbox.sh, etc.) follow the
"1-spawn pattern": shell wrapper calls one python helper that
imports the work module directly.

---

## 3. Tool surface (what the agent calls)

Claude Code exposes tools the agent invokes. Each tool fires
PreToolUse + PostToolUse hooks, so the plugin sees every call.

### Built-in tools (CC core)

| Tool | tool_input key for ident | Notes |
|---|---|---|
| `Bash` | `command` | gated by `pretooluse-bash-gate.sh` |
| `Read` | `file_path` | |
| `Edit` | `file_path` | |
| `Write` | `file_path` | |
| `NotebookEdit` | `file_path` | |
| `Glob` | `pattern` | |
| `Grep` | `pattern` | |
| `Agent` | `subagent_type` or `description` | dispatches a subagent (fires SubagentStop on return) |
| `TaskCreate` | `subject` | |
| `WebFetch` | `url` | |
| `Skill` | `skill` | loads the named skill into context |

### MCP tools

Pattern: `mcp__<server>__<tool>` (e.g. `mcp__plugin_kaizen_kaizen__metrics_session`).

For these, the **tool_name itself IS the identifier** — no need to
dig into tool_input. The plugin's `pretooluse_trace.py` extracts
ident this way:

```python
if tool_name.startswith("mcp__"):
    ident = tool_name
```

### Bash-gate behavior

`hooks/claude/pretooluse-bash-gate.sh` intercepts Bash tool calls.
Returns `permissionDecision: "ask"` for destructive operations:

- `rm -rf` outside `/tmp|/var/tmp|~/.cache|$TMPDIR|$HOME/.cache`
- `git push --force`
- `git reset --hard`
- `git clean -fd`
- `git rm` without `KAIZEN_ALLOW_DELETE=1`

Bypass: `KAIZEN_BASH_GATE_DISABLE=1`.

### MCP server pattern (plugin-authored)

Plugin-authored MCP servers live at
`skills/workflow/scripts/<feature>_mcp.py` as PEP 723 shebang scripts:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.0", "fastmcp"]
# ///

from fastmcp import FastMCP
mcp = FastMCP("kaizen-<feature>")

@mcp.tool()
async def my_tool(arg: str) -> dict:
    """Docstring drives MCP-side schema."""
    return {...}

if __name__ == "__main__":
    mcp.run()
```

Registration:

- `plugins/kaizen/.mcp.json` lists every MCP server
- `plugins/kaizen/.claude-plugin/plugin.json::permissions.allow`
  needs `Bash(uv run --script ${CLAUDE_PLUGIN_ROOT}/.../X_mcp.py:*)`

### Trace flow for tool calls (the whole picture)

```
User submits prompt
  ↓
UserPromptSubmit hook chain fires
  ↓ (inbox capture, brain trigger, intent suggest, ...)
Model picks a tool, generates tool_use block
  ↓
PreToolUse hook fires (gate + trace)
  ↓
Tool executes (CC core or MCP server)
  ↓
PostToolUse hook fires (trace + bash-commit suggest + drain inbox)
  ↓
(loop) Model may call more tools …
  ↓
Stop hook fires (ralph loop / backlog reminder / karpathy gate / context notifier / auto handoff)
  ↓
Assistant turn ends — next prompt or session end
```

Each transition writes a trace event (`trace.py append_event`) +
a dxm mirror entry (`_dxm_emit`). The dxm log is the per-session
audit trail; the trace log is the cross-session activity index.

---

## 4. Env-var index

| Env | Effect | Set by |
|---|---|---|
| `CLAUDE_PLUGIN_ROOT` | CC sets at hook fire time | Claude Code |
| `CLAUDE_PROJECT_DIR` | repo root for the session | Claude Code |
| `KAIZEN_PLUGIN_ROOT` | manual override (fallback) | user |
| `KAIZEN_TRACE_DIR` | trace log location | user |
| `KAIZEN_TRACE_DISABLE` | mute all trace.py | user |
| `KAIZEN_DXM_DIR` | dxm log location | user |
| `KAIZEN_DXM_DISABLE` | mute dxm | user |
| `KAIZEN_METRICS_DISABLE` | mute metrics rollup | user |
| `KAIZEN_BASH_GATE_DISABLE` | disable pretooluse-bash-gate | user |
| `KAIZEN_SESSION_INTAKE_DISABLE` | skip SessionStart QA | user |
| `KAIZEN_AUTO_HANDOFF_DISABLE` | skip threshold-based block | user |
| `KAIZEN_<HOOK>_DISABLE` | per-hook bypass (every hook honors this) | user |
| `KAIZEN_ALLOW_DELETE` | per-command override for `git rm` | user |

---

## 5. Schema-validation hooks for plugin authors

When wiring a new feature, validate against:

- `surface validate` — runs `kaizen surface validate` (orphan hooks, missing perms, unmounted MCP)
- `iron-laws check` — runs `kaizen iron-laws check --all` (12+ structural laws)
- `gatekeeper check --staged` — aggregates iron-laws + etu + plugin-validator
- `test pipeline` — `bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh`

Iron-law-blocking issues will fail the pre-commit gate.
