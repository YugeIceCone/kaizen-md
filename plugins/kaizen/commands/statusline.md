---
name: statusline
description: Install or inspect the kaizen statusline — a one-line status bar showing context window usage, backlog state (in flight + next up), and gate state (cached vs ready). Wires into Claude Code's `statusLine` config in ~/.claude/settings.json. Subcommands: install | preview | path | uninstall.
argument-hint: [preview|install|path|uninstall]
---

# kaizen statusline

!`case "${ARGUMENTS:-preview}" in
  install)
    SETTINGS_PATH="$HOME/.claude/settings.json"
    SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/statusline.sh"
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
    echo '{"total_tokens": 95000}' | bash "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/statusline.sh"
    echo ""
    echo "(Run with /kaizen:statusline install to see real install instructions.)"
    ;;
  path)
    echo "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/statusline.sh"
    ;;
  uninstall)
    echo "Remove the 'statusLine' key from $HOME/.claude/settings.json."
    ;;
  *)
    echo "usage: /kaizen:statusline [preview|install|path|uninstall]"
    ;;
esac`
