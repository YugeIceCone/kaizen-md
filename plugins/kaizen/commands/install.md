---
name: install
description: Install the kaizen pre-commit gate in the current git repo (local-only, never global).
---

Install the kaizen gate into the current repo.

Run the installer:

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/install.sh`

The installer:
1. Creates `.kaizen/hooks/` and symlinks `pre-commit` to the plugin's script
2. Sets `git config core.hooksPath .kaizen/hooks` (LOCAL only — never touches global config)
3. Auto-detects workflow-state dir (`.workflow/`, `docs/workflow/`, or repo root) for `backlog_path`
4. Writes a starter `.kaizen.toml` if absent (compile cmd auto-detected from stack)
5. Seeds an empty `backlog.json` + renders `backlog.md`
6. Adds `.kaizen/` to `.gitignore`

After install, smoke-test:

!`git commit --allow-empty -m 'test(gate): smoke test'`

A clean gate run looks like:
- `✓ compile barrier`
- `✓ Conventional Commits prefix`
- `✓ backlog: .md matches .json (no drift)`
- exit 0

Uninstall: `git config --unset core.hooksPath && rm -rf .kaizen/`
