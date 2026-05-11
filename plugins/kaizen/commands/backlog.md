---
name: backlog
description: View or mutate the project's kaizen backlog (JSON-sourced, .md is generated). Usage:[list|in_flight|next_up|done|parked|add ...|start BK-N|tick BK-N|park BK-N|decision]
---

# kaizen backlog

The backlog is the single rolling source for micro work — items with a probe + verify hook. JSON is the source of truth at `<workflow_dir>/backlog.json`; the `.md` view at `<workflow_dir>/backlog.md` is auto-regenerated on every mutation.

## Argument router

Parse `$ARGUMENTS`:

- **No args** or `list` → run:
  !`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backlog.py list all`
- `in_flight` / `next_up` / `done` / `parked` → list that section:
  !`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backlog.py list $ARGUMENTS`
- `show BK-N` → print one item as JSON:
  !`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backlog.py show BK-N`
- `add ...` → forward to backlog.py (the user provides `--title`, `--probe`, `--verify` and optional `--ref`, `--tags`, `--section`):
  !`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backlog.py add $ARGUMENTS`
- `start BK-N` / `tick BK-N` / `park BK-N` / `unpark BK-N` → state transitions:
  !`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backlog.py $ARGUMENTS`
- `decision --text "..." [--why "..."]` → append a one-liner decision
- `render` → regenerate the `.md` view
- `verify` → CI-style drift check (exit non-zero if `.md` drifted from `.json`)

For any other input, **don't guess** — print the CLI help:

!`python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/backlog.py --help`

## Item shape

```
- [ ] BK-NNN  <verb-first title>  *(ref)*  — probe: <cmd> — verify: <cmd>  [tags]
```

`probe` proves the item stays micro (≤3 files, 0 manifest edits, 0 trait moves). `verify` proves the work is done. Don't accept items without both.

## Sizing reminder

NEVER grade in hours. Probe with grep / cargo-tree / ast-grep / language-LSP "references". Threshold: ≤3 files = micro; 4–15 = split into siblings; ≥16 or structural-manifest edit = promote to `plans/<date>-<slug>.md`. Full thresholds in the `kaizen` skill PART 1.
