# Wiring Recipes

Copy-paste blocks for `~/.claude/settings.json` (global) or `<project>/.claude/settings.json` (per-project). Project settings merge over global.

## Skeleton

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "bash /abs/path/to/script.sh" }
        ]
      }
    ]
  }
}
```

## Recipe 1 — Inject project context on every session

```json
"SessionStart": [{
  "matcher": "*",
  "hooks": [{
    "type": "command",
    "command": "bash $HOME/.claude/scripts/inject-context.sh session"
  }]
}]
```

The script must emit:
```json
{ "hookSpecificOutput": { "hookEventName": "SessionStart", "additionalContext": "..." } }
```

## Recipe 2 — Block dangerous Bash commands

```json
"PreToolUse": [{
  "matcher": "Bash",
  "hooks": [{
    "type": "command",
    "command": "python3 $HOME/.claude/scripts/bash-guard.py"
  }]
}]
```

`bash-guard.py`:
```python
import json, re, sys
ev = json.load(sys.stdin)
cmd = ev.get("tool_input", {}).get("command", "")
if re.search(r'rm\s+-rf\s+/(\s|$)|:\(\)\{|mkfs', cmd):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked destructive command: {cmd!r}"
        }
    }))
else:
    print("{}")
```

## Recipe 3 — Force-continue on Stop (auto=yes workflows)

```json
"Stop": [{
  "matcher": "*",
  "hooks": [{
    "type": "command",
    "command": "bash $HOME/.claude/skills/workflow/scripts/workflow.sh stop-hook"
  }]
}]
```

`stop-hook` reads state, and if a workflow is `auto=yes` and not at last stage, prints:
```json
{ "decision": "block", "reason": "Workflow is mid-routine; advance to <next stage>." }
```
Otherwise prints `{}` and exits.

## Recipe 4 — Auto-format on edit

```json
"PostToolUse": [{
  "matcher": "Edit|Write|MultiEdit",
  "hooks": [{
    "type": "command",
    "command": "bash $HOME/.claude/scripts/auto-format.sh"
  }]
}]
```

The script reads `tool_input.file_path` and runs `prettier --write` / `ruff format` / `gofmt -w` per extension, then emits:
```json
{ "hookSpecificOutput": { "hookEventName": "PostToolUse", "additionalContext": "Formatted X with prettier." } }
```

## Recipe 5 — Scan prompts for secrets

```json
"UserPromptSubmit": [{
  "matcher": "*",
  "hooks": [{
    "type": "command",
    "command": "python3 $HOME/.claude/scripts/scan-secrets.py"
  }]
}]
```

```python
import json, re, sys
ev = json.load(sys.stdin)
p = ev.get("prompt", "")
if re.search(r'(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,})', p):
    print("Potential API key in prompt — redact before sending.", file=sys.stderr)
    sys.exit(2)  # exit 2 sends stderr to Claude as a block reason
```

## Recipe 6 — Snapshot before compaction

```json
"PreCompact": [{
  "matcher": "*",
  "hooks": [{
    "type": "command",
    "command": "bash $HOME/.claude/skills/workflow/scripts/workflow.sh pre-compact"
  }]
}]
```

Pair with a `SessionStart` hook that reads the snapshot when `source=compact`.

## Recipe 7 — Auto-advance subagent

```json
"SubagentStop": [{
  "matcher": "*",
  "hooks": [{
    "type": "command",
    "command": "bash $HOME/.claude/skills/workflow/scripts/workflow.sh subagent-stop"
  }]
}]
```

See [auto-advance-pattern.md](auto-advance-pattern.md) for full state-machine flow.

## Multiple matchers per event

You can stack independent matchers — all matching ones run:

```json
"PreToolUse": [
  { "matcher": "Bash", "hooks": [{"type":"command","command":"bash-guard.sh"}] },
  { "matcher": "Edit|Write", "hooks": [{"type":"command","command":"path-guard.sh"}] },
  { "matcher": "mcp__.*", "hooks": [{"type":"command","command":"mcp-audit.sh"}] }
]
```

## Settings precedence

Highest wins:
1. Enterprise managed (`/etc/claude-code/managed-settings.json`)
2. Command-line flags
3. Local project (`<proj>/.claude/settings.local.json`)
4. Shared project (`<proj>/.claude/settings.json`)
5. User global (`~/.claude/settings.json`)

Hook arrays from **all levels merge**, so a global Stop hook plus a project Stop hook both fire.

## Environment available to hooks

- `$CLAUDE_PROJECT_DIR` — set when running inside a plugin or project context
- stdin: full event JSON
- working dir: project root (or cwd Claude was started in)

## Plugin-distributed hooks

Plugins can ship hooks via `${CLAUDE_PLUGIN_ROOT}` in their `plugin.json`:

```json
{
  "hooks": {
    "Stop": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/stop.sh" }] }]
  }
}
```

The harness expands `${CLAUDE_PLUGIN_ROOT}` to the plugin's install directory at run time.
