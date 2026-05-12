# Hooks Configuration for `/workflow`

Wire `scripts/workflow.sh` into Claude Code hooks to make the workflow self-driving in `auto=yes` mode and resumable across sessions.

All snippets go in `~/.claude/settings.json` (user-global) or `<project>/.claude/settings.local.json` (project-scoped). The hooks API is JSON-over-stdin/stdout — see Claude Code docs for the full schema.

## Required: Stop hook (auto=yes self-driving)

When `auto=yes` and a stage just finished, Claude would normally stop and wait for the user. The Stop hook reads `.kaizen/workflow/state.json` and emits `decision: block` to keep Claude going.

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash $HOME/.claude/skills/workflow/scripts/workflow.sh stop-hook"
          }
        ]
      }
    ]
  }
}
```

**Behavior:**

- No state file → emits `{}` → Claude stops normally.
- State file exists, `auto_mode=no` → emits `{}` → Claude stops normally.
- State file exists, `auto_mode=yes`, current stage is set → emits `{"decision": "block", "reason": "..."}` → Claude continues with a system reminder telling it to run the next stage.
- All stages complete → emits `{}` → Claude stops normally with a final report.

## Optional: SessionStart hook (auto-resume)

If a previous session left a workflow mid-flight, this hook injects a system reminder so Claude knows to resume.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'STATE=\"${CLAUDE_PROJECT_DIR:-.}/.kaizen/workflow/state.json\"; [ -f \"$STATE\" ] && echo \"{\\\"hookSpecificOutput\\\":{\\\"hookEventName\\\":\\\"SessionStart\\\",\\\"additionalContext\\\":\\\"Active workflow detected. Run: bash $HOME/.claude/skills/workflow/scripts/workflow.sh status — and use the workflow-routing skill to resume.\\\"}}\" || echo \"{}\"'"
          }
        ]
      }
    ]
  }
}
```

## Optional: PreToolUse hook (scope guard)

When a workflow is mid-flight, prevent edits to files outside the current stage's expected scope. This is conservative and may produce false-positive blocks; use only if you've had scope-creep issues.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash $HOME/.claude/skills/workflow/scripts/workflow.sh scope-guard"
          }
        ]
      }
    ]
  }
}
```

(Note: the `scope-guard` subcommand is a future extension. The current script does not implement it; document and add only if needed.)

## Risks & Mitigations

- **Hook errors hang the session.** A buggy script that prints non-JSON crashes the hook chain. Mitigation: the `stop-hook` subcommand always emits valid JSON (defaulting to `{}` on any error path).
- **Auto-mode runs longer than expected.** Stop-hook keeps the session live until the routine completes. Pair with a Bash timeout or budget cap if running unattended.
- **Concurrent state writes.** If two terminals use the same project at the same time, both can advance the same workflow. The script does not lock — keep one workflow per project.
- **Plugin path drift.** When this skill is loaded as part of a plugin, `${CLAUDE_PLUGIN_ROOT}` resolves to the plugin's directory. The slash command at `~/.claude/commands/workflow.md` uses `${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/workflow}` to handle both cases.

## Verifying the hook chain

```bash
# Confirm the script runs
bash $HOME/.claude/skills/workflow/scripts/workflow.sh

# Confirm Stop hook output (should be {} when no state)
echo '{"event":"Stop"}' | bash $HOME/.claude/skills/workflow/scripts/workflow.sh stop-hook

# Confirm Stop hook output mid-workflow
bash $HOME/.claude/skills/workflow/scripts/workflow.sh init "test prompt auto=yes"
echo '{"event":"Stop"}' | bash $HOME/.claude/skills/workflow/scripts/workflow.sh stop-hook
# Should emit a {"decision":"block",...} response.

# Cleanup
bash $HOME/.claude/skills/workflow/scripts/workflow.sh reset
```

## Disabling the hook

Remove the Stop entry from `settings.json`, or set `auto=no` on every workflow run. With `auto=no`, the Stop hook still runs but emits `{}` (no-op).

## Wiring into a plugin

If this skill is packaged as part of a plugin, the plugin's `hooks.json` would carry the same Stop hook entry, but with `${CLAUDE_PLUGIN_ROOT}` instead of `$HOME/.claude/skills/workflow`:

```json
{
  "Stop": [
    {
      "matcher": "*",
      "hooks": [
        {"type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/workflow.sh stop-hook"}
      ]
    }
  ]
}
```
