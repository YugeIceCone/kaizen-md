# Changelog

All notable changes to the `kaizen` plugin documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [1.1.2] — 2026-05-11

### Fixed

- **Slash commands no longer run unintended subcommands.** The "argument router" pattern (6 commands had it: `backlog`, `backup`, `migrate`, `disable-dupes`, `publish`, `uninstall`) had multiple ``!`...`...`bash` blocks per command markdown, intending only one to fire based on `$ARGUMENTS`. But Claude Code evaluates ALL fenced bash blocks in command markdown — so `/publish` (no args) ran `publish.sh reset` and errored, `/backup` ran `backup.sh restore` without an id, etc.

  Fix: each command now has exactly ONE bash invocation that dispatches via `$ARGUMENTS` directly to the underlying script's subcommand router. Scripts handle empty-args defaults internally (status / list / scan).

### Verified

- `grep -cE '!\`(bash|python|node)' commands/*.md` → all 13 commands have exactly 1 dispatch.
- /kaizen:test → 30/30 still pass.

## [1.1.1] — 2026-05-11

### Fixed

- **`hooks/hooks.json` schema** — wrapped in top-level `{"hooks": {...}}` record per Claude Code's strict validator. Without the wrapper, `/doctor` reported `Hook load failed: expected record, received undefined at path "hooks"`. All 6 hook events (SessionStart×2, UserPromptSubmit, PreToolUse, PostToolUse, Stop, PreCompact) now load correctly.

### Changed

- **`/kaizen:doctor` renamed to `/kaizen:health`** — frees up the `/doctor` slash command for Claude Code's built-in plugin diagnostic. The underlying script is still named `doctor.sh`; only the user-facing command name changed.

## [1.1.0] — 2026-05-11

### Added

- **Doctor command** (`/kaizen:doctor` + `scripts/doctor.sh`) — diagnostic health check across 7 sections (config, hook, scripts, schema, plugin bundle, memory, backups). Exit 1 on errors, 0 otherwise.
- **Uninstall command** (`/kaizen:uninstall` + `scripts/uninstall.sh`) — clean reverse of install; dry-run default; auto-backs up before mutation; preserves backlog + backups.
- **Help command** (`/kaizen:help`) — slash-command aggregator + onboarding flow.
- **Flow command** (`/kaizen:flow` + `scripts/flow_demo.py`) — pocketflow Node+Flow demo (ReadBacklog → Analyze → Report) against the project's own backlog.
- **MCP server** (`scripts/mcp_server.py` + `.mcp.json`) — fastmcp server exposing 10 backlog tools (list, show, add, start, tick, park, unpark, decision, render, verify). Auto-wired on plugin install.
- **Gate Check #9** — committed-secret detection in `pre-commit.sh`. High-confidence regex for AWS keys, GitHub tokens, OpenAI sk-, Slack xox, Google AIza, JWTs, BEGIN PRIVATE KEY. Bypass: `KAIZEN_ALLOW_SECRET=1`.
- **Shared library** (`scripts/lib.sh`) — `realpath_f`, `repo_root`, `toml_get`, `color_init`, `log_*`, `find_sibling` for future DRY-up.
- **Python unit tests** (`tests/test_backlog.py`) — 14 tests covering envelope, next_id, render, round-trip, fmt_item. Wired into the test pipeline.
- **CI workflow** (`.github/workflows/test.yml`) — runs on Linux + macOS; checks bash syntax, Python parse, JSON validity, frontmatter, pipeline test, GNU-only utility ban.
- **Issue templates** — bug, feature, attribution.
- **Pull request template** — sizing-rule probe + checklist.
- **Bundle-refresh procedure** in `CONTRIBUTING.md`.
- **README quickstart** — 3-step onboarding at the top.
- **CONTRIBUTING.md** — sizing rule, commit discipline, PR checklist, cross-platform requirements.

### Changed

- `install.sh` post-install message now lists the full slash-command surface (status, help, disable-dupes, backlog, doctor, backup, uninstall).
- `install.sh` creates `.gitignore` if missing before adding the `.kaizen/` line.
- `backlog.py render` now persists `.json` if missing (catches the install-then-list flow).
- All scripts replace GNU `readlink -f` with `python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))"` — macOS BSD compatible.
- `disable-skill.sh` replaces GNU `find -printf '%f\n'` with shell-glob.
- `hooks.json` extended with PreToolUse(Bash), PostToolUse(Bash), Stop, PreCompact handlers.
- `LICENSE` trimmed to MIT core; bundled-content credits moved to `ATTRIBUTIONS.md`.
- `marketplace.json` + `plugin.json` author/homepage/repository updated to `github.com/YugeIceCone/kaizen-md`.

### Fixed

- `install.sh` skipped `.gitignore` line when the file didn't pre-exist.
- `uninstall.sh` `KEEP_CONFIG` default inverted — would have deleted `.kaizen.toml` by default; now correctly preserves it (only `--remove-config` deletes).
- `precompact-snapshot.sh` `backup.sh` path resolution broken when `$CLAUDE_PLUGIN_ROOT` unset; now uses 3-tier search via `readlink -f` (since portable-replaced with python3).

### Verified

- 30/30 pipeline tests pass (was 29 + 1 unit-test invocation in v1.1).
- 14/14 Python unit tests pass (`python3 tests/test_backlog.py`).
- All scripts pass `bash -n`; all Python passes `ast.parse`.
- All JSON manifests valid.
- Zero GNU-only utilities remaining in shell scripts.
- Doctor on shodan: 1 warning (hook not activated), 0 errors.

### Bundle (unchanged from v1.0.0)

- 9 coding-skills © Jordan Coin Jackson (github.com/JordanCoin/codingskills, MIT)
- 14 superpowers © Jesse Vincent (github.com/obra/superpowers, MIT)
- 5 remember skills + 10 scripts + refs + assets + config © Gabi Fratica (github.com/remember-md/remember, MIT)
- workflow-routing, onion-ddd-workflow, tdd — see ATTRIBUTIONS.md

## [1.0.0] — 2026-05-11

### Added

- **Skill** `kaizen` — 7-part discipline (sizing rule, BACKLOG model, 9-item gate, hook integration, skill weaving, memory hooks, Iron Laws).
- **Pre-commit gate** (`scripts/pre-commit.sh`) — 9 checks: compile barrier, Conventional Commits prefix, structural-change → architecture-log row, plan-file → checkbox tick, `git rm` → memory belief scan, CLAUDE.md no-sha guard, paired-test for new code (soft), backlog `.md` drift vs `.json` (CI gate), project-specific verify. Routes to relevant skills when their domain is touched.
- **Backlog CLI** (`scripts/backlog.py`) — JSON-sourced (`backlog.json`) micro-work tracker with auto-generated `.md` view. Subcommands: `list / show / add / start / tick / park / unpark / decision / render / verify`.
- **Slash commands** (8) — `install`, `gate`, `backlog`, `migrate`, `backup`, `status`, `disable-dupes`, `test`.
- **Hooks** (6 lifecycle events wired): SessionStart×2 (backlog surface + remember context), UserPromptSubmit (capture-keyword), PreToolUse(Bash) (destructive-command gate), PostToolUse(Bash) (auto-tick suggestion), Stop (in_flight reminder), PreCompact (auto-backup).
- **Migration tooling** (`scripts/migrate.sh`) — scan + retire-loose-skill + retire-marketplace + convert-backlog + migrate-backlog-to-workflow. Dry-run default.
- **Backup tooling** (`scripts/backup.sh`) — create / list / show / restore / prune. Auto-fires on pre-deletion, pre-compact, pre-migrate.
- **Disable tooling** (`scripts/disable-skill.sh`) — reversibly toggle loose-skill discovery via SKILL.md ↔ SKILL.md.disabled rename.
- **Test pipeline** (`scripts/test-pipeline.sh`) — TAP-style end-to-end smoke (29 checks, ~1s, low token cost).
- **Bundled skills (32)** — self-contained, no external plugin dependencies:
  - This plugin's `kaizen` skill
  - TDD + 9 coding-skills (kiss, yagni, solid, dry, separation-of-concerns, law-of-demeter, boy-scout-rule, convention-over-configuration, detect-stack) + onion-ddd-workflow
  - 14 superpowers (using-superpowers, brainstorming, writing-plans, executing-plans, subagent-driven-development, dispatching-parallel-agents, test-driven-development, systematic-debugging, verification-before-completion, requesting-code-review, receiving-code-review, finishing-a-development-branch, using-git-worktrees, writing-skills)
  - workflow-routing (the `/workflow` engine)
  - 5 remember/Second Brain skills (remember, process, evolve, status, init) + 10 supporting scripts at `${CLAUDE_PLUGIN_ROOT}/scripts/`
- **Templates** — `REMEMBER.md.template` for user-customizable brain config; `config.defaults.json` for remember scripts.
- **Cross-platform support** — scripts work on Linux GNU + macOS BSD (python3-based path resolution replaces GNU `readlink -f`; shell-glob replaces GNU `find -printf`).

### Notes

- Plugin is self-contained — install does not require `coding-skills`, `superpowers`, `workflow-routing`, or `remember-md` plugins as prerequisites.
- All destructive operations auto-backup before mutating state.
- The pre-commit gate is per-clone (local `core.hooksPath`); never modifies global git config.
