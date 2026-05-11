---
name: install
description: Install the kaizen pre-commit gate in the current git repo (local-only, never global).
---

# kaizen install

Activate the kaizen pre-commit gate in this repo. **Local-only** (per-clone `core.hooksPath`); never touches global git config.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/install.sh`

## What the installer does

1. Creates `.kaizen/hooks/` and symlinks `pre-commit` → the plugin's `pre-commit.sh`
2. Sets `git config core.hooksPath .kaizen/hooks` (LOCAL only)
3. Auto-detects workflow-state dir (`.workflow/`, `docs/workflow/`, or repo root) for `backlog_path`
4. Writes a starter `.kaizen.toml` if absent
5. Seeds `.workflow/backlog.json` + renders `.workflow/backlog.md`
6. Adds `.kaizen/` to `.gitignore`

After install: smoke-test with `git commit --allow-empty -m 'test(gate): smoke'`. Uninstall via `/kaizen:uninstall`.
