---
name: setup
description: Unified kaizen setup command. Subcommands - install (per-repo pre-commit gate, default), uninstall (reverse it), cache (per-repo hash-cache CRUD). Flags --enable-all / --with-* / --no-* run the curated project + global stack. Folds the former /kaizen:install + /kaizen:uninstall + /kaizen:enable-all + /kaizen:cache.
argument-hint: "[install|uninstall|cache ...] [--enable-all] [--with-index] [--with-browser] [--with-daemon] [--with-trace-proxy] [--no-globals] [--no-project] [--dry-run]"
---

# kaizen setup

One entry point for activating, deactivating, and inspecting kaizen in
this repo. **Local-only** (per-clone `core.hooksPath`); never touches
global git config.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/setup.sh $ARGUMENTS`

## Subcommands

| Invocation | What runs |
|---|---|
| `/kaizen:setup` *(or)* `/kaizen:setup install` | Per-repo gate (pre-commit + commit-msg hooks, `.kaizen.toml`, backlog seed) + a cache check. Default. |
| `/kaizen:setup --enable-all` | The gate **plus** the curated global stack (disable-dupes, statusline, shell env). Any `--with-*` / `--no-*` flag also triggers this path. |
| `/kaizen:setup uninstall` | Reverse per-repo activation. Default dry-run; `--execute` to apply, auto-backs up first. Does NOT uninstall the plugin (use `/plugin uninstall`). |
| `/kaizen:setup cache [stats\|key\|get\|put\|delete\|clear]` | Inspect / mutate the per-repo hash cache at `<repo>/.kaizen/cache/`. No arg = `stats`. |

## Opt-in flags (forwarded to the `--enable-all` path)

- `--with-index` — knowledge + trace + onboard indexers (slow first run)
- `--with-browser` — Playwright + Chromium (~200MB download)
- `--with-daemon` — crontab entry for hygiene + cache-refresh
- `--with-trace-proxy` — HTTP proxy wrapping CC → Anthropic
- `--no-globals` — skip the curated global stack (project only)
- `--no-project` — skip per-repo install (globals only)
- `--dry-run` — print what would run, don't execute

## What the per-repo install does

1. Creates `.kaizen/hooks/` and symlinks `pre-commit` + `commit-msg` → the plugin's hook scripts
2. Sets `git config core.hooksPath .kaizen/hooks` (LOCAL only)
3. Auto-detects workflow-state dir (priority: `.kaizen/workflow/` post-v1.22 unify, then legacy `.workflow/`, then `docs/workflow/`, greenfield defaults to `.kaizen/workflow/`)
4. Writes a starter `.kaizen.toml` if absent
5. Seeds `.kaizen/workflow/backlog.json` + renders `backlog.md` at the detected location
6. Writes `.kaizen/.gitignore` per-dir policy (ignores ephemeral cache/hooks/trace/, tracks durable workflow/ artifacts)
7. Cache check — surfaces the per-repo `.kaizen/cache/` state

After install: smoke-test with `git commit --allow-empty -m 'test(gate): smoke'`. Reverse with `/kaizen:setup uninstall`.

## The cache subcommand

`/kaizen:setup cache` is the per-repo hash-keyed JSON cache at
`<repo>/.kaizen/cache/` — hash-invalidated, no TTL. Used by the
compile-barrier check to skip redundant `cargo check` / `tsc --noEmit`
runs when staged content is unchanged, and by agents to memoize
verdicts by diff sha. Programmatic access via the `kaizen-state` MCP
server: `state_cache_stats()` returns `{count, bytes, dir, exists}`.
Mutating ops (`put`, `delete`, `clear`) stay slash-only.
