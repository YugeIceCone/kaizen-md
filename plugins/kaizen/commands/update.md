---
name: update
description: Single-command kaizen maintenance — `git pull` the marketplace, refresh Claude Code's plugin cache, optionally prune old version slots. Subcommands: (none = pull+refresh) | check | prune | path. Replaces the manual `cd marketplace + git pull + /kaizen:refresh-cache` dance.
---

# kaizen update

One command for the full maintenance flow.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/update.sh ${ARGUMENTS:-pull}`

## What it does (default = `pull`)

1. `git ls-remote origin master` — peek at upstream HEAD (no fetch).
2. Compare local HEAD vs remote. Report "up to date" or "N commits behind".
3. If behind: `git pull --ff-only origin master`. Refuses non-ff pulls — surface, don't blindly merge.
4. Run `refresh-cache.sh` to sync the version-named cache slot (always, so local hand-edits also land in cache).
5. Print next step: `/reload-plugins`.

## Subcommands

| arg | effect | exits |
|---|---|---|
| (none) or `pull` | full flow above | 0 on success, 1 on pull failure |
| `check` | read-only: report status, no git mutation, no cache write | 0 if up-to-date, 1 if behind |
| `prune` | remove old cache version slots, keep newest N (default 2) | 0 |
| `path` | print the marketplace directory | 0 |

## Env

- `KAIZEN_MARKETPLACE` — override the marketplace dir (default: `~/.claude/local-marketplaces/kaizen-md`)
- `KAIZEN_KEEP_VERSIONS` — prune retention count (default: 2 — current + 1 previous)

## Typical session

```
/kaizen:update check       # "5 commits behind"
/kaizen:update             # pulls, refreshes cache
/reload-plugins            # activate new commands/hooks/agents
/kaizen:update prune       # later, drop the stale v1.4.0/v1.4.1 cache slots
```

## When to use

- Right after a kaizen release lands on origin (pre-emptive `/kaizen:update check` tells you)
- After hand-editing files in `~/.claude/local-marketplaces/kaizen-md/` (`refresh-cache.sh` re-runs even on no-pull, so local edits flush to cache too)
- Periodically — combine with `/kaizen:status` for an overall health snapshot

## Why this exists

Pre-v1.4.3 maintenance was:

```
cd ~/.claude/local-marketplaces/kaizen-md
git fetch origin
git log HEAD..origin/master       # is there anything?
git pull origin master
/kaizen:refresh-cache
/reload-plugins
```

Six steps, three CLI contexts. `/kaizen:update` collapses to two:

```
/kaizen:update
/reload-plugins
```
