---
name: backup
description: Snapshot workflow state (.kaizen/, legacy .workflow/, .kaizen.toml, optionally brain + project memory) to ~/.claude/backups/kaizen/<repo-slug>/<UTC>.tar.gz. List / restore / prune.
---

# kaizen backup

Snapshot the gate-managed state so destructive ops are reversible. Repo-slugged + UTC-timestamped.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backup.sh ${ARGUMENTS:-list}`

## Subcommands

- (no args) or `list` → list backups for this repo
- `list --all-repos` → list across all repos
- `create [--label LABEL] [--include-brain] [--include-memory]`
- `show <id>` → print contents
- `restore <id>` → restore (auto-saves current state as `pre-restore-<id>` first)
- `prune [--keep N]` → default keep last 10

Always includes (whichever exist): `.kaizen.toml`, `.kaizen/` (post-v1.22 canonical), `.workflow/` (pre-v1.22 legacy). Optional via `--include-brain` / `--include-memory`. Location: `~/.claude/backups/kaizen/<repo-slug>/<UTC>[-label].tar.gz`.
