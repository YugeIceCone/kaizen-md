---
name: install
description: Install the kaizen pre-commit gate in the current git repo (local-only, never global).
---

# kaizen install

Activate the kaizen pre-commit gate in this repo. **Local-only** (per-clone `core.hooksPath`); never touches global git config.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/install.sh`

## What the installer does

1. Creates `.kaizen/hooks/` and symlinks `pre-commit` + `commit-msg` → the plugin's hook scripts
2. Sets `git config core.hooksPath .kaizen/hooks` (LOCAL only)
3. Auto-detects workflow-state dir (priority: `.kaizen/workflow/` post-v1.22 unify, then legacy `.workflow/`, then `docs/workflow/`, greenfield defaults to `.kaizen/workflow/`)
4. Writes a starter `.kaizen.toml` if absent
5. Seeds `.kaizen/workflow/backlog.json` + renders `backlog.md` at the detected location
6. Writes `.kaizen/.gitignore` per-dir policy (ignores ephemeral cache/hooks/trace/, tracks durable workflow/ artifacts)

After install: smoke-test with `git commit --allow-empty -m 'test(gate): smoke'`. Uninstall via `/kaizen:uninstall`.
