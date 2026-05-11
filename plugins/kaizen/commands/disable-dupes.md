---
name: disable-dupes
description: Find and reversibly disable duplicate skills (loose ~/.claude/skills/X vs bundled in this plugin) by renaming SKILL.md ↔ SKILL.md.disabled. Default is dry-run; --execute applies. Fully reversible.
---

# kaizen disable-dupes

Reversibly hide loose-side duplicates so the plugin's bundled version is the only one in the available-skills list. Mechanism: rename `SKILL.md` → `SKILL.md.disabled`. Files stay in place; one rename restores.

## Why disable instead of retire?

| Action | What it does | Reversibility |
|---|---|---|
| **disable-dupes** (this) | Renames `SKILL.md` → `SKILL.md.disabled` in place | One rename back |
| **migrate retire-loose-skill** | Moves whole dir to `~/.claude/skills/.retired/<name>-<TS>/` | One `mv` back |

Disable is the lower-commitment first move. Retire is for after you've verified the plugin version covers everything.

## Argument router

Parse `$ARGUMENTS`:

- **No args** or `scan` → list all duplicates and their state:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/disable-skill.sh scan`
- `disable <skill> [--loose|--plugin]` → disable one side (default: loose):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/disable-skill.sh disable $ARGUMENTS`
- `enable <skill> [--loose|--plugin]` → re-enable:
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/disable-skill.sh enable $ARGUMENTS`
- `list-disabled` → show currently-disabled skills (both sides):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/disable-skill.sh list-disabled`
- `all-loose-dupes [--execute]` → disable every loose-side duplicate at once (dry-run default):
  !`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/disable-skill.sh all-loose-dupes $ARGUMENTS`
- `all-loose-dupes --restore [--execute]` → re-enable all loose-side disables in one call

For any other input, print help:

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/disable-skill.sh --help`

## Safety

- **No file moves.** Only rename in place — the file system layout is unchanged.
- **Dry-run by default** for batch operations.
- **One-line restore** — Claude (or you) can re-enable any disabled skill with a single `enable` call.
- **No deletions ever.** This command never `rm`s — per the no-deletions rule. If you want full removal, use `/kaizen:migrate retire-loose-skill` (which `mv`s to `.retired/` after auto-backup).

## Typical flow after plugin install

```
1. /plugin marketplace add ~/.claude/local-marketplaces/kaizen-md
2. /plugin install kaizen@kaizen-md
3. /kaizen:disable-dupes scan                    # see what duplicates
4. /kaizen:disable-dupes all-loose-dupes         # dry-run preview
5. /kaizen:disable-dupes all-loose-dupes --execute   # apply
6. (verify everything still works via plugin namespace)
7. /kaizen:migrate retire-loose-skill <name> --execute   # when ready to truly retire (still reversible via .retired/)
```

## Notes

- The `--plugin` side is rarely the right choice (you'd be hiding the bundled version). Useful only if a project has a strong reason to prefer the loose one.
- `/plugin disable kaizen` would hide the whole plugin (all 32 bundled skills + slash commands). Use this command instead for surgical per-skill control.
