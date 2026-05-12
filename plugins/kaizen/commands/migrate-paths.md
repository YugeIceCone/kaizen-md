---
name: migrate-paths
description: Migrate kaizen's pre-v1.22 scattered state into the unified ~/.claude/.kaizen/ layout (user-global) and <repo>/.kaizen/workflow/ (project-side). Idempotent — already-migrated paths are no-ops. Auto-invoked by /kaizen:install and /kaizen:enable-all so most users never need to run this directly.
---

# kaizen migrate-paths

One-shot mover from the v1.21-and-earlier scatter to the v1.22.0+ unified layout.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/migrate_paths.sh ${ARGUMENTS}`

## What it moves

**User-global** (`~/.claude/`):

| Legacy                          | New                               |
|---------------------------------|-----------------------------------|
| `.kaizen-trace/`                | `.kaizen/trace/`                  |
| `.kaizen-knowledge/`            | `.kaizen/knowledge/`              |
| `.kaizen-daemon/`               | `.kaizen/daemon/`                 |
| `kaizen-inbox/`                 | `.kaizen/inbox/`                  |
| `backups/kaizen/`               | `.kaizen/backups/`                |
| `kaizen-schemas/`               | `.kaizen/schemas/`                |

**Project-side** (`<repo>/`):

| Legacy                          | New                               |
|---------------------------------|-----------------------------------|
| `.workflow/` (state + backlog)  | `.kaizen/workflow/`               |
| `.workflow/schemas/`            | `.kaizen/workflow/schemas/`       |

Also rewrites `<repo>/.kaizen.toml` if `backlog_path` / `architecture_log` still reference `.workflow/`.

## Flags

| Flag                      | Effect                                                  |
|---------------------------|---------------------------------------------------------|
| `--dry-run`               | Print intended moves, change nothing.                   |
| `--force`                 | Overwrite NEW paths if they already exist (rare).       |
| `--user-only`             | Skip the project-side migration.                        |
| `--project-only`          | Skip the user-global migration.                         |
| `--project-root <path>`   | Override the auto-detected repo root.                   |

## Behaviour on conflicts

If both legacy AND new paths exist (e.g. you started using a new install before migrating), the migrator **skips** the move and surfaces a warning. Use `--force` to overwrite the new with the legacy (rare — usually you want to keep the new).

## When you'd run it manually

- After upgrading from kaizen v1.21 or earlier to v1.22+, if `/kaizen:install` wasn't re-run.
- To inspect what would change in a dry-run before committing.
- To migrate the project side only on a multi-repo machine after the global side is already done.

For all other cases, `/kaizen:install` and `/kaizen:enable-all` invoke this automatically.

## Idempotency

Safe to run multiple times. After a successful run, legacy dirs are gone and new dirs hold the data; subsequent runs find nothing to move and report `0 moved, N skipped`.
