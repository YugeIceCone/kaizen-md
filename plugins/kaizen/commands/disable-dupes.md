---
name: disable-dupes
description: Find and reversibly disable duplicate skills (loose ~/.claude/skills/X vs bundled in this plugin) by renaming SKILL.md ↔ SKILL.md.disabled. Default is dry-run; --execute applies. Fully reversible.
---

# kaizen disable-dupes

Reversibly hide loose-side duplicates so plugin's bundled version wins. Mechanism: rename `SKILL.md` ↔ `SKILL.md.disabled` in place. Files stay; one rename restores.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/disable-skill.sh ${ARGUMENTS:-scan}`

## Subcommands

- (no args) or `scan` → list duplicates + state
- `disable <skill> [--loose|--plugin]` → disable one side (default: loose)
- `enable <skill> [--loose|--plugin]` → re-enable
- `list-disabled` → show currently-disabled skills
- `all-loose-dupes [--execute]` → batch-disable every loose-side duplicate
- `all-loose-dupes --restore [--execute]` → re-enable all loose-side disables

## vs `/kaizen:migrate retire-loose-skill`

| | disable-dupes | retire-loose-skill |
|---|---|---|
| Action | rename `SKILL.md` ↔ `.disabled` | `mv` to `.retired/<name>-<TS>/` |
| Reversibility | 1 rename | 1 `mv` |
| Use first | ✓ low-commitment cleanup | After plugin verified |

No deletions ever (per pref-no-deletions).
