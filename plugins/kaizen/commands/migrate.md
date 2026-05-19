---
name: migrate
description: "Migrate from loose skills / separate plugins / non-canonical layouts to canonical kaizen shape. Auto-backs up before any destructive op. Default dry-run."
---

# kaizen migrate

Safe transitions between layouts. **Default is dry-run.** Pass `--execute` to apply. Every destructive op auto-backs up first.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/migrate/migrate.sh ${ARGUMENTS:-scan}`

## Subcommands

- (no args) or `scan` → list all migration candidates
- `retire-loose-skill <name> [--execute]` → move `~/.claude/skills/<name>` to `~/.claude/skills/.retired/`
- `retire-marketplace <name>` → print instructions (no auto-uninstall)
- `convert-backlog <md-path> [--execute]` → parse hand-written BACKLOG.md → JSON items
- `migrate-backlog-to-workflow [--execute]` → root BACKLOG.md → `.workflow/backlog.{json,md}`
- `paths [--execute]` → pre-v1.22 path restructure (idempotent). Old `/kaizen:migrate-paths` is now a deprecated alias for this.

Move-not-rm. Plugin uninstall is manual via `/plugin uninstall`.
