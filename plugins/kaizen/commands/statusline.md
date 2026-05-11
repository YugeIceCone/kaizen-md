---
name: statusline
description: Install or inspect the kaizen statusline — a one-line status bar showing context window usage, backlog state (in flight + next up), and gate state (cached vs ready). Wires into Claude Code's `statusLine` config in ~/.claude/settings.json. Subcommands: install | preview | path | uninstall.
---

# kaizen statusline

A single-line status bar that surfaces three things at a glance:

- **🟢/🟡/🔴 context window** — `42k/200k (21%)` — colour by zone (<60 green, <80 yellow, >=80 red)
- **🔵/⚪ backlog state** — `🔵 1 in flight (4↑)` or `⚪ 5 next up`
- **🟢/💾 gate state** — `🟢 gate` (installed, no cache) or `💾 gate (3 cached)`

!`case "${ARGUMENTS:-preview}" in
  install)
    SETTINGS_PATH="$HOME/.claude/settings.json"
    SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/statusline.sh"
    echo "Add this to $SETTINGS_PATH (top-level object):"
    echo ""
    echo '  "statusLine": {'
    echo '    "type": "command",'
    echo "    \"command\": \"bash $SCRIPT\""
    echo '  }'
    echo ""
    echo "Then reload Claude Code. The statusline appears at the bottom of the UI."
    ;;
  preview)
    echo "Preview output (synthetic context + real backlog state):"
    echo ""
    echo '{"total_tokens": 95000}' | bash "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/statusline.sh"
    echo ""
    echo "(Run with /kaizen:statusline install to see real install instructions.)"
    ;;
  path)
    echo "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/statusline.sh"
    ;;
  uninstall)
    echo "Remove the 'statusLine' key from $HOME/.claude/settings.json."
    ;;
  *)
    echo "usage: /kaizen:statusline [preview|install|path|uninstall]"
    ;;
esac`

## How the statusline works

1. Claude Code spawns the configured command for every status refresh.
2. Claude Code passes a JSON event on stdin: model, session_id, total_tokens, etc.
3. The script parses stdin, reads local state (`.workflow/backlog.json`, `.kaizen/cache/`), composes one line, prints to stdout.
4. Designed to render in <50 ms — no network, no LLM calls, just file I/O + JSON parse.

## What it reads (all read-only)

- **stdin** — Claude Code's statusline JSON (for `total_tokens`).
- **`$CLAUDE_CONTEXT_TOKENS` env** — fallback if stdin doesn't carry tokens (some harnesses use this).
- **`<repo>/.kaizen.toml`** — `backlog_path` config field (resolves backlog location).
- **`<repo>/.workflow/backlog.json`** — counts `in_flight` + `next_up` items.
- **`<repo>/.kaizen/cache/`** — counts cached entries for the gate badge.
- **`<repo>/.kaizen/hooks/pre-commit`** symlink — proof the gate is installed.

## Customise

Set env vars in your shell rc (or in the `statusLine.command` itself):

- `KAIZEN_CONTEXT_LIMIT=200000` — change the token-limit reference (default 200k = Opus 4.7 1M-context tier).
- `KAIZEN_STATUSLINE_NO_GATE=1` — hide the gate badge.

(Currently only `KAIZEN_CONTEXT_LIMIT` is honoured by the underlying scripts; `KAIZEN_STATUSLINE_NO_GATE` is a future hook.)
