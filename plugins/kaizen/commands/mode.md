---
name: mode
description: "DEPRECATED ALIAS — use `/kaizen:session-mode` instead (plural intent + matches the bin `kaizen-session-mode`). Set this session's mode (loop | workflow | neither) and pick discipline bundles via QA."
argument-hint: "loop | workflow | neither"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-session-mode:*)", "AskUserQuestion"]
---

# /kaizen:mode (deprecated alias)

**Use `/kaizen:session-mode` instead.** The slash command was `mode`
but the bin wrapper is `kaizen-session-mode`; this alias keeps the
old name working. Follow the full QA pattern documented in
`commands/session-mode.md`.

Run the canonical command — same flow, same outcome:

`/kaizen:session-mode $ARGUMENTS`
