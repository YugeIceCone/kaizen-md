# `hooks/` — provider-categorized hook scripts

## Layout

```
hooks/
├── hooks.json         # Claude Code manifest (canonical location)
├── claude/            # Scripts invoked by Claude Code's hook system
│   ├── _trace.sh
│   ├── _bash_discipline_scan.py
│   ├── session-surface-backlog.sh
│   ├── userprompt-inbox.sh
│   ├── pretooluse-bash-gate.sh
│   ├── posttooluse-bash-commit.sh
│   ├── posttooluse-drain-inbox.sh
│   ├── stop-backlog-reminder.sh
│   ├── precompact-snapshot.sh
│   ├── subagentstop-trace.sh
│   ├── sessionend-drain.sh
│   ├── notification-surface.sh
│   └── karpathy-gate.sh
└── (future) codex/    # Will hold Codex CLI hook scripts when ported
    └── ...
```

## Why categorize

The plugin is now portable to non-Claude-Code hosts (see
`plans/2026-05-13-cross-cli-portability-analysis.md` + the
`bin/kaizen-export --target codex` adapter). Hook events are
host-specific:

- **Claude Code** fires: `SessionStart`, `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStop`, `SessionEnd`,
  `PreCompact`, `Notification`.
- **Codex CLI** fires a different (overlapping) set: `SessionStart`,
  `PreToolUse`, `PostToolUse`, `Stop`, `SessionGoalUpdate`.

Same hook BEHAVIOR (drain inbox, surface backlog, trace event) can
back both providers, but the JSON envelope schemas and event names
differ. Per-provider subdirectories let us share the BEHAVIOR (via
`scripts/_*.sh` helpers or by symlinking) while letting each
provider's manifest reference its own envelope-aware entry point.

## Conventions

- **`hooks.json` stays at the plugin's `hooks/` root.** Claude Code's
  plugin loader discovers the manifest there; moving it would break
  auto-discovery.
- **Commands in `hooks.json` reference `${CLAUDE_PLUGIN_ROOT}/hooks/claude/<name>.sh`**.
  Future providers add their own manifest variant (e.g. shipped via
  `bin/kaizen-export --target codex`) referencing `hooks/codex/<name>.sh`.
- **Cross-CLI-portable helpers** (`_trace.sh`, `_bash_discipline_scan.py`,
  the `_plugin_root.sh` resolver) live alongside the provider scripts
  that consume them. If a helper is genuinely shared across providers,
  it moves to `skills/workflow/scripts/` instead.
- **Tests reference manifest paths** rather than hardcoding script
  names — they auto-pick up provider categorization changes.

## Adding a new provider

When porting a new host:

1. Create `hooks/<provider>/` (e.g. `hooks/codex/`).
2. Copy or symlink the scripts that share behavior across providers.
3. Author host-specific scripts under the new dir.
4. Either:
   - ship a separate manifest at `hooks/<provider>/hooks.json` if
     that host expects per-provider manifest discovery, OR
   - extend `bin/kaizen-export --target <provider>` to emit the
     host's expected manifest format from `hooks/<provider>/`.
5. Tests under `tests/test_<provider>_hooks_wireup.py` mirror the
   shape of `tests/test_cc_hooks_wireup.py`.
