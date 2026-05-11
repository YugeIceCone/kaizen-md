---
name: env
description: Print or install the kaizen shell environment (KAIZEN_ROOT + KAIZEN_SCRIPTS + aliases). Sourcing the env file makes `kaizen-flow`, `kaizen-docs`, `kaizen-backlog`, `kaizen-cache`, `kaizen-context`, `kaizen-inbox`, `kaizen-rules` directly callable from your shell. Subcommands: print | install [bash|zsh] | path | uninstall.
---

# kaizen env

Make kaizen scripts callable from any interactive shell (not just inside Claude Code, where `${CLAUDE_PLUGIN_ROOT}` is auto-set).

!`case "${ARGUMENTS:-print}" in
  print)
    cat "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/kaizen-env.sh"
    ;;
  path)
    echo "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/kaizen-env.sh"
    ;;
  install|install-bash)
    SRC="${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/kaizen-env.sh"
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
    SRC="${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/kaizen-env.sh"
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
            # Remove the two kaizen lines (comment + source) — keep a backup
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

## What the env exports

| Var | Value |
|---|---|
| `KAIZEN_ROOT` | plugin root (where `.claude-plugin/` lives) |
| `KAIZEN_SCRIPTS` | `$KAIZEN_ROOT/skills/kaizen/scripts/` |
| `$PATH` | prepended with `$KAIZEN_SCRIPTS` |

## Aliases (interactive shells)

| Alias | Wraps |
|---|---|
| `kaizen-flow [workspace]` | async Node+Flow demo (parallel docs scan) |
| `kaizen-docs scan` | generic workspace docs generator |
| `kaizen-backlog` | backlog CLI |
| `kaizen-cache` | per-repo cache |
| `kaizen-context` | context-window state |
| `kaizen-inbox` | message inbox |
| `kaizen-rules` | brain-sourced behaviour rules |

## Quick test

After install + shell reload:

```bash
kaizen-flow .        # async pipeline on current workspace
kaizen-docs detect   # list packages
kaizen-inbox stats   # inbox counts
echo $KAIZEN_ROOT    # plugin path
```

## Why this exists

Inside Claude Code, `${CLAUDE_PLUGIN_ROOT}` is auto-set when hooks/skills run. In your regular shell it's not — so `python3 ${CLAUDE_PLUGIN_ROOT}/skills/...` expanded to `/skills/...` and failed. `KAIZEN_ROOT` solves the same problem for interactive use.

## Uninstall

`/kaizen:env uninstall` strips the source line from `.bashrc` + `.zshrc` (with timestamped backups). Or hand-edit and remove the two `# kaizen — shell env` lines.
