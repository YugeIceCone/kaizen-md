---
name: kaizen-hook
description: Catalog + dispatch hub for the kaizen-md plugin's 52 lifecycle hooks across 12 Claude Code events (SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Stop / PreCompact / SubagentStop / SessionEnd / Notification / InstructionsLoaded / PostCompact / CwdChanged). Tells you which event a hook fires on, where each handler lives, how the trace flow works, and how to add a new hook safely. Pairs with claude-hooks (authoring discipline) and intent (declarative automation). Triggers on "which kaizen hook", "what fires on SessionStart", "add a new hook", "hook lifecycle", "kaizen hook flow", "PreToolUse handler", "PostToolUse handler", "hook trace", "hook bypass knob".
---

# kaizen-hook — Plugin Hook Surface Catalog

## ⚠ Iron Law — read in full

Skip nothing. Hook ordering MATTERS (some hooks depend on earlier
hooks' state; e.g. session-intake runs before brain-context inject).
Hook BYPASS knobs MATTER (every hook honors a `KAIZEN_<HOOK>_DISABLE`
env so users can opt out per-hook). Adding a new hook without these
breaks the convention.

## 12 events kaizen hooks into

Authoritative registry: `plugins/kaizen/hooks/hooks.json`. Live per-event
counts via `kaizen-hook-coverage` or `surface.py validate` (handler counts
drift on every new hook; the table below documents purpose only).

| Event | Purpose |
|---|---|
| `SessionStart` | Surface backlog/CLI/context; intake; dxm; token-bloat; detect-stack; brain Persona inject; systems check |
| `UserPromptSubmit` | Brain capture nudge (Python port of upstream user_prompt); inbox; brain-user-prompt; context inject; dxm |
| `PreToolUse` | Bash gate; brain-redirect; trace; write-atomic |
| `PostToolUse` | Trace; keepalive; observer-capture; webfetch-capture; roundtrip-detect; drain-inbox; bash-commit |
| `Stop` | Backlog reminder; karpathy check; self-improving review; ralph-loop stop |
| `PreCompact` | Gold-precompact (mine learnings before context compaction) |
| `SubagentStop` | Subagent-stop trace |
| `SessionEnd` | Token-bloat scan; session-end trace; gold mine; inbox drain; brain session-end |
| `Notification` | Push notify (optional) |
| `InstructionsLoaded` | Trace which @imports loaded |
| `PostCompact` | Refresh auto-load.md after compaction |
| `CwdChanged` | Memory-sync on dir change |

## Hook handlers — where they live

- **Shell handlers** (`*.sh`) — `plugins/kaizen/hooks/claude/`. Most
  are thin wrappers that exec a Python script + trace via `_trace.sh`.
- **Python handlers** (`*.py`, prefixed `_*` for private) —
  `plugins/kaizen/hooks/claude/`. Direct stdin-read + processing.
- **Hot-path handlers** (consolidated Python entry-points) —
  `plugins/kaizen/scripts/handlers/{pretooluse_*, posttooluse_*,
  stop_*, subagentstop_*, userprompt_*, context_notifier, session_start,
  user_prompt}.py`.

The `hooks/claude/` shell scripts MAY shell into the script-dir Python
handlers (e.g. `pretooluse-trace.sh` execs `python3 .../pretooluse_trace.py`).
Or they may inline the work themselves when small.

## Common hook patterns

### 1. Trace-only hook (most common)

```bash
#!/usr/bin/env bash
# foo-trace.sh — record one trace event for the event-type
[ "$KAIZEN_TRACE_DISABLE" = "1" ] && exit 0
source "$(dirname "${BASH_SOURCE[0]}")/_trace.sh"
trace_event "hook" "<EventName>" "$@"
exit 0
```

### 2. Stdin-reading hook (Python)

```python
#!/usr/bin/env python3
"""Reads event JSON from stdin, processes, may emit additionalContext."""
import json, sys
event = json.load(sys.stdin)
# ... handle ...
print(json.dumps({"hookSpecificOutput": {...}}))
```

### 3. Hook with decision output (Stop / PreToolUse)

```python
# Output {"decision": "block", "reason": "..."} to BLOCK the action
# Output {"systemMessage": "..."} to SOFT-NUDGE
# Output "{}" (empty JSON) to allow normally
```

## Bypass knobs (convention)

Every hook honors `KAIZEN_<HOOK_NAME>_DISABLE=1` or a broader category
disable. Examples:

- `KAIZEN_TRACE_DISABLE=1` — turn off all trace hooks
- `KAIZEN_BACKLOG_DISABLE=1` — turn off backlog reminder
- `KAIZEN_INBOX_DISABLE=1` — turn off inbox capture
- `KAIZEN_BRAIN_REDIRECT_DISABLE=1` — turn off brain-redirect nudge
- `KAIZEN_METRICS_DISABLE=1` — turn off metrics emission
- `KAIZEN_DAEMON_<X>_DISABLE=1` — turn off specific daemon job

Iron-law `hook-bypass-knob` (hard, auto) ENFORCES every new hook
declares its bypass knob.

## Adding a new hook (checklist)

1. **Pick the event** — match the user-intent shape.
2. **Write the handler** — shell or Python; under `hooks/claude/`
   (lifecycle wrapper) OR `scripts/handlers/<event>_<name>.py`
   (hot-path Python).
3. **Register in `hooks/hooks.json`** — under the right event, with
   matcher (usually `"*"`) + timeout (be conservative — 5s default).
4. **Add the bypass knob** — `KAIZEN_<NAME>_DISABLE=1` honored before
   any work.
5. **Add to permissions** — `plugin.json::permissions.allow` (or rely
   on the `bash hooks/claude/*.sh:*` / `python3 .../scripts/*.py:*`
   wildcards).
6. **Add a test** — `tests/test_<name>_hook.py` or
   `tests/test_<name>.py`.
7. **Trace integration** — call `_trace.sh trace_event` (shell) or
   `trace.append_event` (Python) so the hook is observable via
   `kaizen-trace search --kind hook`.

## Observability

- `kaizen-hook-coverage` — every hook script on disk should appear in
  hooks.json (orphan detection).
- `kaizen-hook-trace-coverage` — every registered hook should emit at
  least one trace event when fired.
- `kaizen-hook-cascade` — visualize hook chain per event.
- `kaizen-trace search --kind hook` — query the trace log for hook fires.

## Pairing with siblings

| Sibling | Relationship |
|---|---|
| `claude-hooks` | Authoring discipline + Claude Code's hook semantics. Read FIRST when designing a new hook. |
| `intent` | Declarative phrase + event_pattern → action automation. Sits ABOVE hooks; uses hook fires as triggers. |
| `kaizen-trace` (planned) | Trace surface for hook observability. |
| `iron-laws` | `hook-bypass-knob` rule enforced via gatekeeper. |

## Triggers (when to load this skill)

- About to write a new hook + need the event + handler shape
- Debugging hook ordering / cascade issues
- Auditing hook coverage / orphans / trace gaps
- Understanding which hook fires for a given event
- Looking up the bypass knob for a hook

## DON'T load when

- Just RUNNING the plugin (hooks fire transparently)
- Designing automation rules (load `Skill(intent)` instead)
- Modifying skill bodies (hooks are orthogonal)
