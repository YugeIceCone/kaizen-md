---
name: install
description: Install the kaizen pre-commit gate in this repo. Pass --enable-all (or any --with-*/--no-* flag) for the broader project + global setup.
argument-hint: "[--enable-all] [--with-index] [--with-browser] [--with-daemon] [--with-trace-proxy] [--no-globals] [--no-project] [--dry-run]"
---

# kaizen install

Activate the kaizen pre-commit gate in this repo. **Local-only** (per-clone `core.hooksPath`); never touches global git config.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/install.sh $ARGUMENTS`

## Two modes (one entry point)

| Invocation | What runs |
|---|---|
| `/kaizen:install` | Just the per-repo gate (pre-commit + commit-msg hooks, `.kaizen.toml`, backlog seed). Default. |
| `/kaizen:install --enable-all` | Same as above **plus** the curated global stack (disable-dupes, statusline, shell env). Equivalent to the legacy `/kaizen:enable-all`. |

The `--enable-all` flag (and any `--with-*` / `--no-*` flag) delegates to `enable_all.sh` which calls back into `install.sh` for the per-repo step.

## Opt-in flags (forwarded when --enable-all is set)

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

After install: smoke-test with `git commit --allow-empty -m 'test(gate): smoke'`. Uninstall via `/kaizen:uninstall`.

## Back-compat

`/kaizen:enable-all` still works (unchanged). Both `/kaizen:enable-all` and `/kaizen:install --enable-all` invoke the same `enable_all.sh` script.
