---
name: hygiene
description: Run kaizen hygiene checks + safe auto-cleanups. Five checks: prune old cache versions, prune old backup tarballs, purge drained inbox entries, validate brain rules, re-render drifted backlog.md. On-demand cousin of /kaizen:daemon (which runs the same checks on cron). Subcommands: check (default) | fix | check-<name> | fix-<name> | json.
---

# kaizen hygiene

On-demand hygiene checks + auto-applicable safe cleanups.

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/util/hygiene.py ${ARGUMENTS:-check}`

## Checks

| Name | What it checks | What `fix` does |
|---|---|---|
| `cache` | `~/.claude/plugins/cache/kaizen-md/kaizen/*` count vs `KAIZEN_KEEP_VERSIONS` (default 2) | rm old version dirs |
| `backups` | `~/.claude/backups/kaizen/<repo>/*.tar.gz` count vs `KAIZEN_KEEP_BACKUPS` (default 10) | rm old tarballs |
| `inbox` | drained `~/.claude/kaizen-inbox/*.json` older than `KAIZEN_INBOX_TTL_DAYS` (default 7) | rm stale entries |
| `rules` | `rules.py validate` (brain-sourced behaviour rules schema) | NONE — surfaces validation errors only (manual edit required) |
| `backlog` | `backlog.py verify` per kaizen-installed repo (md drifted from json) | `backlog.py render` to regenerate md |

## Subcommands

| arg | effect | exit |
|---|---|---|
| (none) or `check` | run all 5 checks, summary line per check | 0 if all ok, 1 if any drift |
| `fix` | run + apply safe cleanups | 0 |
| `check-<name>` | one check, JSON output | 0 if ok, 1 if drift |
| `fix-<name>` | one fix | 0 |
| `json` | full report as JSON (machine-readable, all checks) | 0/1 |
| `--verbose` / `-v` | full JSON dump alongside summary | — |

## Safe-fixes-only policy

These cleanups operate on kaizen-owned state ONLY:
- Cache slots inside `~/.claude/plugins/cache/kaizen-md/`
- Backup tarballs inside `~/.claude/backups/kaizen/`
- Inbox entries inside `~/.claude/kaizen-inbox/`
- Generated backlog `.md` files (re-rendered from authoritative `.json`)

User-owned source code, brain notes, project files, and git history are **never** touched by `fix`. The `rules` check exclusively reports — schema errors require manual edit because the consequences of "guessed fix" are user-specific.

## How it relates to /kaizen:daemon

`/kaizen:daemon` runs `hygiene fix` on a cron schedule (default every 30 min).
`/kaizen:hygiene` runs the same logic on demand. Use whichever fits — both share `hygiene.py`.

## Discover-repos registry

For `backlog` to find your kaizen-installed repos, the daemon writes paths to `~/.kaizen-installs.txt` (one per line). If absent, hygiene falls back to checking `$PWD` only. Touch the file manually if you want hygiene to scan more repos before the daemon's first run:

```
echo "/home/you/workspace/repo1" >> ~/.kaizen-installs.txt
echo "/home/you/workspace/repo2" >> ~/.kaizen-installs.txt
```
