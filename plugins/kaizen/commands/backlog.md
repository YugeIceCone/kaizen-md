---
name: backlog
description: View or mutate the project's kaizen backlog (JSON-sourced, .md is generated). Usage:[list|in_flight|next_up|done|parked|add ...|start BK-N|tick BK-N|park BK-N|decision]
---

# kaizen backlog

JSON-sourced micro-work tracker. `.md` is auto-regenerated on every mutation.

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/backlog.py ${ARGUMENTS:-list all}`

## Subcommands

- (no args) or `list [section]` → list items (sections: `in_flight` / `next_up` / `done` / `parked` / `all`)
- `show <id>` → print one item as JSON
- `add --title T --probe P --verify V [--section S] [--ref R] [--tags A,B]`
- `start <id>` / `tick <id> [--committed SHA]` / `park <id> --reason R` / `unpark <id> [--section S]`
- `decision --text T [--why Y]`
- `render` / `verify`

Item shape: `- [ ] BK-NNN  <verb-first title>  *(ref)*  — probe: <cmd> — verify: <cmd>  [tags]`

Sizing: NEVER hours. Probe with grep/cargo-tree/ast-grep. ≤3 files = micro; 4–15 = split; ≥16 = promote to `plans/<date>-<slug>.md`.
