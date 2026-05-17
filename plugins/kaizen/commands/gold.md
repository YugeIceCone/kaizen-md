---
name: gold
description: Incidental-discovery + learnings tracker. Capture mid-work patterns + gotchas + hidden contracts that would otherwise decay; later `promote` durable ones to CLAUDE.md or a brain Note. Subcommands - capture | list | show | promote | path. Default behavior - emit `list` (the safe read-only view).
argument-hint: "capture <pattern> [...] | list [--unpromoted] | show <id> | promote <id> --to <path> [--brain] | path"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-gold:*)"]
---

# kaizen gold

Catch the "ha!" moments mid-work. Capture immediately so the pattern
doesn't decay; later promote the durable ones to rules (CLAUDE.md) or
beliefs (brain Notes via `--brain`).

!`bash -c 'exec ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-gold ${ARGUMENTS:-list}'`

## Subcommands

- `capture "<pattern>" [--tag X] [--source path:line] [--learned "<ctx>"]` — append a new entry
- `list [--tag X] [--unpromoted] [--limit N] [--json]` — read entries
- `show <id> [--json]` — single entry
- `promote <id> --to <path> [--brain] [--note "<ctx>"]` — graduate an entry
- `path` — print storage path

## Promote destinations

- `--to CLAUDE.md` — append a project-rule bullet
- `--to ~/.claude/.kaizen/brain/Notes/<slug>.md --brain` — create a brain Note (frontmatter + h1 + provenance) when the target doesn't exist
- `--to plans/<slug>.md` — append to a plan file

## Storage

`$KAIZEN_DIR/gold/<project-slug>/patterns.jsonl` — per-project, append-only,
atomic via `_atomic.atomic_append_line`. Inspect with `kaizen gold path`.

## When to capture

Subprocess quirks, hidden contracts, per-dir gotchas, model-aware
surprises — anything you'd warn a future agent about.

See `skills/gold/SKILL.md` for the full skill body.
