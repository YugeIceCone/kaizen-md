---
name: refresh-cache
description: Force Claude Code's plugin cache to match the kaizen source. Solves the "/plugin update doesn't refresh local marketplaces on version bump" gap — /reload-plugins serves stale content otherwise. Subcommands: (none = refresh) | --dry-run | --force.
---

# kaizen refresh-cache

Forces Claude Code's plugin cache to match the source on disk.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/refresh-cache.sh ${ARGUMENTS:-}`

## Why this exists

`/plugin update kaizen@kaizen-md` doesn't reliably refresh local-marketplace plugins on version bump. The cache (`~/.claude/plugins/cache/kaizen-md/kaizen/<VER>/`) stays at the previous version, so `/reload-plugins` continues serving stale commands/skills/hooks.

`/kaizen:refresh-cache` reads the version from your source's `plugin.json`, finds the matching cache slot, and rsyncs the source over it (with `--delete` so removed files in source are removed in cache).

## Usage

| arg | effect |
|---|---|
| (none) | refresh — exits 0 silently if already in sync |
| `--dry-run` | print what would change, no writes |
| `--force` | overwrite even if cache appears in sync |

## When to run

- After pushing a new kaizen release to GitHub (`git push + tag`)
- After hand-editing files in `~/.claude/local-marketplaces/kaizen-md/`
- When `/reload-plugins` shows old behaviour (commands missing, hooks not firing)

## Verification

After running:
```
/reload-plugins
```
Then check the previously-missing commands appear, or that the count of skills/agents/hooks bumps to the expected number.

## Env overrides

- `KAIZEN_PLUGIN_SRC` — alternate source dir (default: `~/.claude/local-marketplaces/kaizen-md/plugins/kaizen`)
- `KAIZEN_CACHE_BASE` — alternate cache base (default: `~/.claude/plugins/cache/kaizen-md/kaizen`)
