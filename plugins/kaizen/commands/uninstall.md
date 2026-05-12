---
name: uninstall
description: Reverse /kaizen:install for this repo. Unsets core.hooksPath, removes .kaizen/, optionally removes config + backlog. Default is dry-run; auto-backs up before mutation. Does NOT uninstall the plugin (use /plugin uninstall for that).
---

# kaizen uninstall (per-repo)

Cleanly remove the plugin's activation from this repo. **Default is dry-run.** Pass `--execute` to apply.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/uninstall.sh $ARGUMENTS`

## Flags

- (no args) → dry-run preview
- `--execute` → perform (auto-backs up first)
- `--remove-backlog` → also delete `.workflow/backlog.{json,md}` (default keeps)
- `--remove-config` → also delete `.kaizen.toml` (default keeps for re-install)

## Does NOT

- Uninstall the plugin (use `/plugin uninstall kaizen@kaizen-md`)
- Delete backups
- Delete `.workflow/progress.md`, `state.json`, or other project / workflow-routing state
