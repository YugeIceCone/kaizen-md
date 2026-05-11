---
name: backup
description: Snapshot workflow state (.workflow/, .kaizen.toml, optionally brain + project memory) to ~/.claude/backups/kaizen/<repo-slug>/<UTC>.tar.gz. List / restore / prune.
---

# kaizen backup

Snapshot the gate-managed state so destructive ops are reversible. Backups are repo-slugged (multi-project safe) and timestamped (UTC ISO).

## Argument router

Parse `$ARGUMENTS`:

- **No args** or `list` → list backups for this repo:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh list`
- `list --all-repos` → list across all repos:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh list --all-repos`
- `create [--label LABEL] [--include-brain] [--include-memory]` → snapshot now:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh create $ARGUMENTS`
- `show <id>` → print contents of a backup:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh show $ARGUMENTS`
- `restore <id>` → restore from a backup (auto-saves current state as pre-restore-<id> first):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh restore $ARGUMENTS`
- `prune [--keep N]` → remove old backups (default keep last 10):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh prune $ARGUMENTS`

## What gets backed up

**Always:**
- `.kaizen.toml` (config)
- `.workflow/` (backlog.json, backlog.md, state.json, snapshot.md, progress.md, decisions.md, audit logs, ...)
- `.kaizen/` (hooks symlink dir)

**Optional flags:**
- `--include-brain` — adds `~/.claude/brain/` (the Second Brain — Persona.md, Notes/, Journal/, MEMORY.md)
- `--include-memory` — adds `~/.claude/projects/<slug>/memory/` (project-specific memory)

## Backup location

```
~/.claude/backups/kaizen/<repo-slug>/<UTC>[-label].tar.gz
```

Repo-slugged paths prevent multi-project collisions. Per-repo `list` is the default.

## Auto-backup hooks

- **Pre-restore.** `backup restore <id>` auto-creates a `pre-restore-<id>` backup of the current state before extracting.
- **Pre-migrate.** Every `migrate.sh --execute` calls `backup create --label <op>` first.
- **Pre-deletion** (gate). When `KAIZEN_ALLOW_DELETE=1` triggers a `git rm` past the pre-deletion gate, the gate auto-creates a backup labeled `pre-delete-<UTC>`.

## Restore recipe

```
# 1. List
backup list
# 2. Inspect a candidate
backup show 20260511T193000Z-myedit
# 3. Restore (current state auto-backed up first)
backup restore 20260511T193000Z-myedit
```
