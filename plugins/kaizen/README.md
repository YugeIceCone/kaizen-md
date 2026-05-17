# kaizen

[![test](https://github.com/YugeIceCone/kaizen-md/actions/workflows/test.yml/badge.svg)](https://github.com/YugeIceCone/kaizen-md/actions/workflows/test.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![version](https://img.shields.io/badge/version-1.39.0-green)](./CHANGELOG.md)

**A Claude Code plugin that gives you a working Second Brain on Day 1.**

```bash
# 1. Install the plugin (one-time)
/plugin marketplace add ~/.claude/local-marketplaces/kaizen-md
/plugin install kaizen@kaizen-md

# 2. Seed a starter brain
kaizen-brain seed default

# 3. Capture your first thought
kaizen-brain capture "we use SQLite over Postgres for local indexes"
```

That's it. You now have:
- A `~/.claude/.kaizen/brain/` populated with Persona + 3 starter Notes + the PARA folder structure (Inbox / Journal / Projects / People / Areas / Resources / Tasks / Templates / Archive)
- A pre-commit gate that scans your brain for deletion-prevention beliefs
- Hooks that auto-capture "remember this" prompts into your brain
- An evolve flow that promotes high-confidence Notes into Persona's Top Beliefs

Read [`assets/starters/default/README.md`](./assets/starters/default/README.md) for what the starter contains + how to customize.

---

## What kaizen actually is

A self-contained plugin that bundles:

1. **A Second Brain** (Persona / PARA / Notes) — owned end-to-end since v1.38.0 (Remember plugin retired, brain migrated under `.kaizen/brain/`).
2. **Git commit discipline** — pre-commit + commit-msg gate enforces compile-clean, structural-change → architecture-log row, `git rm` → memory-belief scan, paired-test for new code, Conventional Commits, plan-file checkbox tick.
3. **A JSON-sourced micro-work backlog** — `.kaizen/workflow/backlog.json` is single source; `.md` view auto-renders.
4. **49 bundled skills** + **22 MCP servers** + **18 lifecycle hooks** + **6 sub-agents** — covering TDD, coding-skills (DRY/KISS/SoC/SOLID/LoD/YAGNI/Boy-Scout/Convention/Karpathy), onion-DDD, workflow routing, audit, brain capture/promote/evolve, and observability across 6 data-stream layers.

It works in any project, any Claude Code session, with no other plugin prerequisites. Cross-platform (Linux GNU + macOS BSD, `python3` only hard runtime dep).

**Stop guessing if a change is "ready to commit".** The pre-commit gate enforces compile-clean, structural-change → architecture-log row, `git rm` → memory-belief scan, no-secrets-in-diff, paired-test for new code, backlog `.md` drift, and per-skill suggestions. The commit-msg gate enforces Conventional Commits prefix + plan-file → checkbox tick (split out from pre-commit in v1.25.1 because git doesn't pre-populate `.git/COMMIT_EDITMSG` for `git commit -m`). Sizing work uses trace + sem + grep, never hours.

**One file = micro work.** `.kaizen/workflow/backlog.json` is the single rolling source of truth. The `.md` view auto-renders. Items have probe + verify hooks. Lifecycle CLI: `add` → `start` → `tick` → `park` / `decision`. Plan files reserved for ≥3-phase work or carve-out triggers.

**Composable, not invasive.** Per-clone hooks (local `core.hooksPath`, never global). Dry-run defaults for destructive ops. Auto-backup before pre-deletion / pre-compact / pre-uninstall. Cross-platform (Linux GNU + macOS BSD, `python3` only hard runtime dep).

## What you get

- **Pre-commit gate** (`scripts/pre-commit.sh`) — staging-state checks: compile barrier, structural-change → architecture-log row, `git rm` → memory belief scan, CLAUDE.md no-sha guard, paired-test for new code (soft), backlog `.md` drift vs `.json` (CI gate), 8+1 coding-skills suggestion engine, dependency-allowlist, project-specific verify. Routes to relevant skills when their domain is touched.
- **Commit-msg gate** (`scripts/commit-msg.sh`, v1.25.1+) — message-dependent checks: Conventional Commits prefix (`feat|fix|refactor|...`, including breaking-change `!:`), plan-file mention → `+- [x]` checkbox tick.
- **Backlog** (`scripts/backlog.py`) — JSON-sourced (`backlog.json`) micro-work tracker with auto-generated `.md` view. Subcommands: `list / show / add / start / tick / park / unpark / decision / render / verify`. Replaces hand-edited `BACKLOG.md`.
- **39 bundled skills** — self-contained discipline. No external plugin dependencies. **All bundled content credited to its original author** — see [ATTRIBUTIONS.md](./ATTRIBUTIONS.md) for full author + source + license details. Quick summary:
  - `kaizen` (this one — the discipline; © YugeIceCone)
  - **TDD + coding (10):** `:detect-stack`, `:kiss`, `:yagni`, `:solid`, `:dry`, `:separation-of-concerns`, `:law-of-demeter`, `:boy-scout-rule`, `:convention-over-configuration` (© Jordan Coin Jackson, github.com/JordanCoin/codingskills), plus `:tdd` and `:onion-ddd-workflow`
  - **Superpowers (14):** `:using-superpowers`, `:brainstorming`, `:writing-plans`, `:executing-plans`, `:subagent-driven-development`, `:dispatching-parallel-agents`, `:test-driven-development`, `:systematic-debugging`, `:verification-before-completion`, `:requesting-code-review`, `:receiving-code-review`, `:finishing-a-development-branch`, `:using-git-worktrees`, `:writing-skills` — © Jesse Vincent, github.com/obra/superpowers
  - **Workflow-routing (1):** `:workflow-routing` (the `/workflow` engine — multi-stage routines, state.json machine)
  - **Remember / Second Brain (5):** `:remember`, `:process`, `:evolve`, `:status`, `:init` — © Gabi Fratica, github.com/remember-md/remember — plus all supporting scripts at `${CLAUDE_PLUGIN_ROOT}/scripts/`
- **Slash commands (38 total)** — `/kaizen:setup`, `/kaizen:backlog`, `/kaizen:precommit`, `/kaizen:models` (v1.26.0, Ollama lifecycle), `/kaizen:audit`, `/kaizen:review`, `/kaizen:knowledge`, `/kaizen:trace-search`, `/kaizen:onboard`, `/kaizen:scrape`, etc. Full list: `/kaizen:menu`.
- **MCP servers (5)** — `kaizen-backlog`, `kaizen-browser` (Playwright), `kaizen-trace-search`, `kaizen-knowledge-search`, `kaizen-onboard-search`. Auto-wired via `.mcp.json`.
- **Lifecycle hooks (6)** — SessionStart surfaces `## In flight` + `## Next up` backlog items; UserPromptSubmit captures input to inbox for mid-sequence visibility; PreToolUse(Bash) gates destructive commands; PostToolUse drains inbox + traces commits; Stop reminds about in_flight items; PreCompact snapshots state.

## Session + project agnostic

The plugin works in any project, any session, with no plugin prerequisites:

- Bundles its dependencies (tdd + coding-skills + onion-ddd-workflow) so the gate's skill-routing always resolves.
- Reads stack via `kaizen:detect-stack` — adapts to Rust / TypeScript / Go / Python / etc. without per-project skill setup.
- `pre-commit.sh` resolves its sibling `backlog.py` via `readlink -f $BASH_SOURCE` — works whether installed at `~/.claude/skills/` standalone OR as a plugin under `~/.claude/local-marketplaces/...`.
- `backlog_path` in `.kaizen.toml` auto-detects `.kaizen/workflow/` (v1.22+ canonical) → `.workflow/` (legacy) → `docs/workflow/` → repo-root per project.
- `core.hooksPath` is set LOCAL only (per-clone) — never touches global git config, never affects unrelated repos.

Optional peers (recommended but not required):
- `workflow-routing` skill (bundled as `kaizen:workflow-routing`) — gate surfaces active-routine hints from `.kaizen/workflow/state.json` when present
- `remember` plugin — pre-deletion gate scans Persona Top Beliefs for deletion-prevention rules
- **Ollama** (`https://ollama.com`) — power `/kaizen:models` + the embedding/chat backends. Optional; the indexers fall back to sentence-transformers if Ollama isn't running.

## Quick start (3 steps)

```
1. /plugin marketplace add ~/.claude/local-marketplaces/kaizen-md
   /plugin install kaizen@kaizen-md           # one-time

2. /kaizen:setup                                  # per-project, idempotent

3. /kaizen:disable-dupes && /kaizen:status    # confirm green
```

That's it. Pre-commit gate fires automatically. Backlog tracker available via `/kaizen:backlog`.

For the full command list: `/kaizen:menu`. For a diagnostic: `/kaizen:health`.

## Install (detail)

`/kaizen:setup` runs `scripts/setup.sh`, which:

1. Symlinks `.kaizen/hooks/{pre-commit,commit-msg}` → the plugin's hook scripts
2. Sets `git config core.hooksPath .kaizen/hooks` **LOCALLY** (per-clone — never touches global config)
3. Writes a starter `.kaizen.toml` (compile cmd auto-detected from stack); auto-detects workflow-state dir at `.kaizen/workflow/` (post-v1.22 canonical) → legacy `.workflow/` → `docs/workflow/` → repo root
4. Seeds `.kaizen/workflow/backlog.json` + renders `backlog.md` at the detected location
5. Writes `.kaizen/.gitignore` (per-dir policy — ignores ephemeral `cache/`, `hooks/`, `trace/`; tracks durable `workflow/` artifacts)
6. Symlinks `bin/kaizen-*` shims into `~/.local/bin/`

`/kaizen:setup uninstall` reverses this cleanly; preserves backlog + backups by default.

## Sizing rule

**Never grade work in hours.** Probe with trace + sem + grep:

- `grep -rE "<symbol>" | wc -l` → file count
- `cargo tree -i -p <crate>` → reverse-deps
- `ast-grep` / language LSP "references" → caller graph

Thresholds:
- ≤3 files, 0 manifest edits, 0 trait moves → micro (backlog item)
- 4–15 files OR 1 manifest/trait → split into sibling micros
- ≥16 files OR ≥2 manifest OR cross-context OR carve-out → promote to `plans/<date>-<slug>.md`

See `skills/workflow/SKILL.md` PART 1 for the full schema.

## `.kaizen/workflow/` namespace (post-v1.22 canonical)

The plugin coexists with the bundled `workflow-routing` skill (the `/workflow` command). Ownership by filename (all under `<repo>/.kaizen/workflow/`):

| File | Owner |
|---|---|
| `state.json` | workflow-routing (its stage machine) |
| `snapshot.md` | workflow-routing (PreCompact snapshot) |
| `backlog.json` | **kaizen** (this plugin) |
| `backlog.md` | **kaizen** (generated view) |
| `progress.md` | project convention (architecture log) |

No cross-write. Shared envelope (`schema_version`, `metadata.created`/`updated`) for future tooling that joins state across skills.

Legacy `<repo>/.workflow/` is recognized for backward compat; `kaizen migrate paths` (auto-invoked by `/kaizen:setup`) moves it to the canonical location.

## Uninstall

```
/kaizen:setup uninstall                          # reverses hooks + symlinks
# OR manually:
git config --unset core.hooksPath          # per-repo
rm -rf .kaizen/                            # per-repo (preserves workflow/ artifacts if you pin them first)
/plugin uninstall kaizen@kaizen-md
```

## Credits

`kaizen` is © 2026 YugeIceCone, MIT-licensed. Several skills started
as adaptations of prior open-source work — extensive kaizen-local
alterations now make them plugin-original derivatives, but the
foundational designs are theirs and the credit stays.

| Origin | Author | Skills derived from it |
|---|---|---|
| [`coding-skills`](https://github.com/JordanCoin/codingskills) | **Jordan Coin Jackson** | `kiss / yagni / dry / solid / separation-of-concerns / law-of-demeter / boy-scout-rule / convention-over-configuration / detect-stack` |
| [`superpowers`](https://github.com/obra/superpowers) v5.1.0 | **Jesse Vincent (obra)** | `using-superpowers / brainstorming / writing-plans / executing-plans / subagent-driven-development / dispatching-parallel-agents / test-driven-development / systematic-debugging / verification-before-completion / requesting-code-review / receiving-code-review / finishing-a-development-branch / using-git-worktrees / writing-skills` |
| [`claude-code-skills`](https://github.com/alirezarezvani/claude-code-skills) | **alirezarezvani** | `code-tour / karpathy / self-improving` |
| [`remember`](https://github.com/remember-md/remember) | **Gabi Fratica** | consolidated into [`brain/`](skills/brain/SKILL.md) (Python rewrite, MCP-exposed); `remember / process / evolve / status / init` remain as back-compat wrappers |

See [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md) for the full per-skill
notes including divergence highlights + license info.

`.kaizen/workflow/backlog.json` is preserved on uninstall — it's project data.
