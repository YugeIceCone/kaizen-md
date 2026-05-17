---
name: env
description: "(Alias for /kaizen:setup env.) Print or install the kaizen shell environment (KAIZEN_ROOT + KAIZEN_SCRIPTS + aliases). Sourcing the env file makes `kaizen-flow`, `kaizen-docs`, `kaizen-backlog`, `kaizen-cache`, `kaizen-context`, `kaizen-inbox`, `kaizen-rules` directly callable from your shell. Subcommands: print | install [bash|zsh] | path | uninstall."
argument-hint: "[print|install|install-zsh|path|uninstall]"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-setup:*)"]
---

# kaizen env (alias for `/kaizen:setup env`)

Folded into `/kaizen:setup env` as part of the 2026-05-18 CLI surface
consolidation. This slash is preserved as a thin alias so existing
muscle memory / scripts keep working.

!`bash "${CLAUDE_PLUGIN_ROOT}/bin/kaizen-setup" env ${ARGUMENTS:-print}`

## Canonical entry points

- Slash:  `/kaizen:setup env [print|install|install-zsh|path|uninstall]`
- CLI:    `kaizen setup env [print|install|install-zsh|path|uninstall]`
- Alias:  `/kaizen:env [...]` (this command — same behavior)
