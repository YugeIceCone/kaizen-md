---
name: uninstall
description: Reverse /kaizen:install for this repo. Unsets core.hooksPath, removes .kaizen/, optionally removes config + backlog. Default is dry-run; auto-backs up before mutation. Does NOT uninstall the plugin (use /plugin uninstall for that).
---

# kaizen uninstall (per-repo)

Cleanly remove the plugin's activation from this repo. **Default is dry-run.**

## Argument router

Parse `$ARGUMENTS`:

- **No args** → dry-run preview:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/uninstall.sh`
- `--execute` → actually perform (auto-backs up first):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/uninstall.sh $ARGUMENTS`
- `--remove-backlog` → also delete `.workflow/backlog.{json,md}` (project data; default keeps)
- `--remove-config` → also delete `.kaizen.toml` (default keeps for re-install)
- `-h` / `--help` → full usage

## What gets removed

| File | Default | Behavior |
|---|---|---|
| `git config core.hooksPath` | ✓ removed | unset (only if set to `.kaizen/hooks`) |
| `.kaizen/` directory | ✓ removed | the symlink dir (regenerated on re-install) |
| `.gitignore` line `.kaizen/` | ✓ removed | reverted |
| `.kaizen.toml` | ✗ kept | pass `--remove-config` to delete |
| `.workflow/backlog.json` / `backlog.md` | ✗ kept | pass `--remove-backlog` to delete |
| `.workflow/progress.md`, `state.json`, ... | ✗ never | project + workflow-routing state |
| `~/.claude/backups/kaizen/<slug>/` | ✗ never | restore source |

## Safety

- **Dry-run by default.** Re-run with `--execute` to apply.
- **Auto-backup** runs before mutation (label `pre-uninstall-<UTC>`).
- **Project data preserved** — backlog content + workflow state survive uninstall by default.

## What this does NOT do

- Does **not** uninstall the plugin from Claude Code. For that:
  ```
  /plugin uninstall kaizen@kaizen-md
  ```
- Does **not** delete the marketplace. For that:
  ```
  /plugin marketplace remove kaizen-md
  ```
- Does **not** delete backups. They live at `~/.claude/backups/kaizen/` and are the restore source.

## Re-activate later

```
/kaizen:install
```

Reads the preserved `.kaizen.toml`, re-creates the symlink + hooksPath.
