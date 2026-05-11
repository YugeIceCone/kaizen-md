# kaizen

[![test](https://github.com/YugeIceCone/kaizen-md/actions/workflows/test.yml/badge.svg)](https://github.com/YugeIceCone/kaizen-md/actions/workflows/test.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![version](https://img.shields.io/badge/version-1.1.4-green)](./CHANGELOG.md)

**Consistent git commit discipline as a Claude Code plugin.** Pre-commit gate (10 checks) + JSON-sourced micro-work backlog + 32 bundled skills + 6 lifecycle hooks + MCP server. Self-contained: no external plugin dependencies.

**Stop guessing if a change is "ready to commit".** The gate enforces compile-clean, Conventional Commits prefix, structural-change → architecture-log row, plan-file → checkbox tick, `git rm` → memory-belief scan, no-secrets-in-diff, paired-test for new code, and backlog/.md drift. Sizing work uses trace + sem + grep, never hours.

**One file = micro work.** `.workflow/backlog.json` is the single rolling source of truth. The `.md` view auto-renders. Items have probe + verify hooks. Lifecycle CLI: `add` → `start` → `tick` → `park` / `decision`. Plan files reserved for ≥3-phase work or carve-out triggers.

**Composable, not invasive.** Per-clone hooks (local `core.hooksPath`, never global). Dry-run defaults for destructive ops. Auto-backup before pre-deletion / pre-compact / pre-uninstall. Cross-platform (Linux GNU + macOS BSD, `python3` only hard runtime dep).

## What you get

- **Pre-commit gate** (`scripts/pre-commit.sh`) — 9 checks: compile barrier, Conventional Commits prefix, structural-change → architecture-log row, plan-file → checkbox tick, `git rm` → memory belief scan, CLAUDE.md no-sha guard, paired-test for new code (soft), backlog `.md` drift vs `.json` (CI gate), project-specific verify. Routes to relevant skills when their domain is touched.
- **Backlog** (`scripts/backlog.py`) — JSON-sourced (`backlog.json`) micro-work tracker with auto-generated `.md` view. Subcommands: `list / show / add / start / tick / park / unpark / decision / render / verify`. Replaces hand-edited `BACKLOG.md`.
- **32 bundled skills** — self-contained discipline. No external plugin dependencies. **All bundled content credited to its original author** — see [ATTRIBUTIONS.md](./ATTRIBUTIONS.md) for full author + source + license details. Quick summary:
  - `kaizen` (this one — the discipline; © YugeIceCone)
  - **TDD + coding (10):** `:detect-stack`, `:kiss`, `:yagni`, `:solid`, `:dry`, `:separation-of-concerns`, `:law-of-demeter`, `:boy-scout-rule`, `:convention-over-configuration` (© Jordan Coin Jackson, github.com/JordanCoin/codingskills), plus `:tdd` and `:onion-ddd-workflow`
  - **Superpowers (14):** `:using-superpowers`, `:brainstorming`, `:writing-plans`, `:executing-plans`, `:subagent-driven-development`, `:dispatching-parallel-agents`, `:test-driven-development`, `:systematic-debugging`, `:verification-before-completion`, `:requesting-code-review`, `:receiving-code-review`, `:finishing-a-development-branch`, `:using-git-worktrees`, `:writing-skills` — © Jesse Vincent, github.com/obra/superpowers
  - **Workflow-routing (1):** `:workflow-routing` (the `/workflow` engine — multi-stage routines, state.json machine)
  - **Remember / Second Brain (5):** `:remember`, `:process`, `:evolve`, `:status`, `:init` — © Gabi Fratica, github.com/remember-md/remember — plus all supporting scripts at `${CLAUDE_PLUGIN_ROOT}/scripts/`
- **Slash commands** — `/kaizen:install`, `/kaizen:backlog`, `/kaizen:gate`.
- **SessionStart hook** — surfaces `## In flight` + `## Next up` backlog items at session start.

## Session + project agnostic

The plugin works in any project, any session, with no plugin prerequisites:

- Bundles its dependencies (tdd + coding-skills + onion-ddd-workflow) so the gate's skill-routing always resolves.
- Reads stack via `kaizen:detect-stack` — adapts to Rust / TypeScript / Go / Python / etc. without per-project skill setup.
- `pre-commit.sh` resolves its sibling `backlog.py` via `readlink -f $BASH_SOURCE` — works whether installed at `~/.claude/skills/` standalone OR as a plugin under `~/.claude/local-marketplaces/...`.
- `backlog_path` in `.kaizen.toml` auto-detects `.workflow/` / `docs/workflow/` / repo-root per project.
- `core.hooksPath` is set LOCAL only (per-clone) — never touches global git config, never affects unrelated repos.

Optional peers (recommended but not required):
- `workflow-routing` plugin (the `/workflow` command) — gate surfaces active-routine hints from `.workflow/state.json` when present
- `remember` plugin — pre-deletion gate scans Persona Top Beliefs for deletion-prevention rules

## Quick start (3 steps)

```
1. /plugin marketplace add ~/.claude/local-marketplaces/kaizen-md
   /plugin install kaizen@kaizen-md           # one-time

2. /kaizen:install                                  # per-project, idempotent

3. /kaizen:disable-dupes && /kaizen:status    # confirm green
```

That's it. Pre-commit gate fires automatically. Backlog tracker available via `/kaizen:backlog`.

For the full command list: `/kaizen:menu`. For a diagnostic: `/kaizen:doctor`.

## Install (detail)

`/kaizen:install` runs `scripts/install.sh`, which:

1. Symlinks `.kaizen/hooks/pre-commit` → the plugin's `pre-commit.sh`
2. Sets `git config core.hooksPath .kaizen/hooks` **LOCALLY** (per-clone — never touches global config)
3. Writes a starter `.kaizen.toml` (compile cmd auto-detected from stack)
4. Seeds `.workflow/backlog.json` + renders `.workflow/backlog.md`
5. Adds `.kaizen/` to `.gitignore`

`/kaizen:uninstall` reverses this cleanly; preserves backlog + backups by default.

## Sizing rule

**Never grade work in hours.** Probe with trace + sem + grep:

- `grep -rE "<symbol>" | wc -l` → file count
- `cargo tree -i -p <crate>` → reverse-deps
- `ast-grep` / language LSP "references" → caller graph

Thresholds:
- ≤3 files, 0 manifest edits, 0 trait moves → micro (backlog item)
- 4–15 files OR 1 manifest/trait → split into sibling micros
- ≥16 files OR ≥2 manifest OR cross-context OR carve-out → promote to `plans/<date>-<slug>.md`

See `skills/kaizen/SKILL.md` PART 1 for the full schema.

## `.workflow/` namespace

The plugin coexists with the `workflow-routing` skill (the `/workflow` command). Ownership by filename:

| File | Owner |
|---|---|
| `.workflow/state.json` | workflow-routing (its stage machine) |
| `.workflow/snapshot.md` | workflow-routing (PreCompact snapshot) |
| `.workflow/backlog.json` | **kaizen** (this plugin) |
| `.workflow/backlog.md` | **kaizen** (generated view) |
| `.workflow/progress.md` | project convention (architecture log) |

No cross-write. Shared envelope (`schema_version`, `metadata.created`/`updated`) for future tooling that joins state across skills.

## Uninstall

```
git config --unset core.hooksPath          # per-repo
rm -rf .kaizen/                       # per-repo
/plugin uninstall kaizen@kaizen-md
```

`.workflow/backlog.json` is preserved on uninstall — it's project data.
