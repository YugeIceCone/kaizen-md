---
name: env
description: Print or install the kaizen shell environment (KAIZEN_ROOT + KAIZEN_SCRIPTS + aliases). Sourcing the env file makes `kaizen-flow`, `kaizen-docs`, `kaizen-backlog`, `kaizen-cache`, `kaizen-context`, `kaizen-inbox`, `kaizen-rules` directly callable from your shell. Subcommands: print | install [bash|zsh] | path | uninstall.
argument-hint: [print|install|install-zsh|path|uninstall]
---

# kaizen env

!`case "${ARGUMENTS:-print}" in
  print)
    cat "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/kaizen-env.sh"
    ;;
  path)
    echo "${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/kaizen-env.sh"
    ;;
  install|install-bash)
    SRC="${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/kaizen-env.sh"
    LINE="# kaizen — shell env + aliases"$'\n'"source \"$SRC\""
    RC="$HOME/.bashrc"
    if grep -qF "kaizen-env.sh" "$RC" 2>/dev/null; then
        echo "  ∘ $RC already sources kaizen-env.sh — nothing to do"
    else
        printf '\n%s\n' "$LINE" >> "$RC"
        echo "  ✓ appended to $RC"
        echo ""
        echo "Reload your shell to pick it up:"
        echo "  source $RC"
    fi
    ;;
  install-zsh)
    SRC="${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/kaizen-env.sh"
    LINE="# kaizen — shell env + aliases"$'\n'"source \"$SRC\""
    RC="$HOME/.zshrc"
    if grep -qF "kaizen-env.sh" "$RC" 2>/dev/null; then
        echo "  ∘ $RC already sources kaizen-env.sh — nothing to do"
    else
        printf '\n%s\n' "$LINE" >> "$RC"
        echo "  ✓ appended to $RC"
        echo ""
        echo "Reload your shell to pick it up:"
        echo "  source $RC"
    fi
    ;;
  uninstall)
    for RC in "$HOME/.bashrc" "$HOME/.zshrc"; do
        if grep -qF "kaizen-env.sh" "$RC" 2>/dev/null; then
            cp "$RC" "$RC.bak-kaizen-env-$(date +%Y%m%dT%H%M%SZ)"
            grep -v -E "(# kaizen — shell env|kaizen-env\.sh)" "$RC" > "$RC.tmp" && mv "$RC.tmp" "$RC"
            echo "  ✓ removed from $RC (backup at $RC.bak-*)"
        fi
    done
    ;;
  *)
    echo "usage: /kaizen:env [print|install|install-zsh|path|uninstall]"
    ;;
esac`
