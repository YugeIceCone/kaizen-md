---
name: migrate
description: Migrate from loose skills / separate plugins / non-canonical layouts to the kaizen plugin's canonical shape. Auto-backs up before any destructive operation. Default is dry-run.
---

# kaizen migrate

Safe transitions between layouts. **Default is dry-run** — nothing changes unless you pass `--execute`. Every destructive op auto-backs up first via `backup.sh`.

## Argument router

Parse `$ARGUMENTS`:

- **No args** or `scan` → list all migration candidates:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/migrate.sh scan`
- `retire-loose-skill <name> [--execute]` → move `~/.claude/skills/<name>` to `~/.claude/skills/.retired/` after backup:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/migrate.sh retire-loose-skill $ARGUMENTS`
- `retire-marketplace <name>` → print instructions (no auto-uninstall — UX action via `/plugin`):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/migrate.sh retire-marketplace $ARGUMENTS`
- `convert-backlog <md-path> [--execute]` → parse a hand-written `BACKLOG.md` → JSON-source items:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/migrate.sh convert-backlog $ARGUMENTS`
- `migrate-backlog-to-workflow [--execute]` → move root-level `BACKLOG.md` → `.workflow/backlog.{json,md}`:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/migrate.sh migrate-backlog-to-workflow $ARGUMENTS`

For any other input, print help:

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/migrate.sh --help`

## What the scan surfaces

1. **Loose skills overlapping bundled equivalents** — `~/.claude/skills/{tdd,kiss,dry,...}` that this plugin now bundles. After plugin install they'll appear under both `kaizen:<name>` (plugin) AND the bare `<name>` (loose). Retire loose to dedupe.
2. **Marketplaces with bundled equivalents** — e.g. `remember-md`. The 5 remember skills + scripts are bundled here; the separate marketplace becomes redundant.
3. **Non-canonical BACKLOG locations** — `BACKLOG.md` at repo root should move to `.workflow/backlog.{json,md}` to sit alongside `progress.md`/`state.json`/`snapshot.md`.
4. **Standalone `kaizen` skill** — the loose `~/.claude/skills/kaizen/` from before plugin install.

## Safety

- **Dry-run is default.** Migrations never fire silently.
- **Auto-backup before mutation.** Every destructive op calls `backup.sh create --label <op>` first.
- **Move, never rm.** Loose skills move to `~/.claude/skills/.retired/<name>-<TS>/`. Restore is one `mv` away.
- **Plugin uninstall is manual.** This command prints `/plugin uninstall` instructions; never auto-uninstalls (that's a Claude Code UX action).
- **The no-deletion rule applies.** When in doubt, scan + ask for explicit confirmation before `--execute`.
