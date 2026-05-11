# Changelog

All notable changes to the `kaizen` plugin documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [1.5.0] — 2026-05-11

### Added — auto-daemon + hygiene cleanups

Cron-driven background worker that keeps the kaizen install healthy without manual intervention. Each tick (default every 30 min):

1. **Hash-compare** plugin source vs Claude Code's cache → auto `refresh-cache` on drift
2. **Read remote HEAD** via `git ls-remote` (network-light, no fetch). Notify-only by default — auto-pull is opt-in via `KAIZEN_DAEMON_AUTOPULL=1` (untrusted upstream code is a real risk)
3. **Run hygiene fixes** — safe cleanups on kaizen-owned state only

**`scripts/daemon.py`** — one-shot worker, cron-friendly. Subcommands:
- `run` — single tick (cron uses this)
- `install [--interval N]` — add crontab entry (default 30 min)
- `uninstall` — remove crontab entry
- `status` — cron state + last-run + log tail
- `log [N]` — tail last N log lines

State + log at `~/.claude/.kaizen-daemon/{state.json,log}`.

**`scripts/hygiene.py`** — five checks, on-demand via `/kaizen:hygiene` or auto via daemon:

| Check | Drift trigger | Auto-fix |
|---|---|---|
| `cache` | >`KAIZEN_KEEP_VERSIONS` (2) version dirs | rm old slots |
| `backups` | >`KAIZEN_KEEP_BACKUPS` (10) tarballs per repo | rm old tarballs |
| `inbox` | drained entries >`KAIZEN_INBOX_TTL_DAYS` (7d) | rm stale entries |
| `rules` | `rules.py validate` fails | NONE — surfaces only (manual edit) |
| `backlog` | `backlog.py verify` fails per repo | `backlog.py render` (regenerate .md) |

Subcommands: `check` (default), `fix`, `check-<name>`, `fix-<name>`, `json`, `--verbose`.

**Safe-fixes-only policy**: cleanups operate exclusively on kaizen-owned state (cache slots, backup tarballs, inbox entries, generated backlog.md). User source / brain notes / project files / git history are never touched.

**`bin/kaizen-daemon` + `bin/kaizen-hygiene`** — auto-symlinked into `~/.local/bin/` by `/kaizen:install` (the v1.4.2 zero-config feature). Available as `kaizen daemon ...` (multiplexer) and `kaizen-daemon` (direct).

**Discover-repos registry** at `~/.kaizen-installs.txt` — daemon writes paths there so hygiene's backlog check knows which repos to scan. Hand-add lines if you want hygiene to scan more before the daemon's first run.

### Lifecycle

```
/kaizen:daemon install --interval 30    # add cron entry
/kaizen:daemon status                    # see runs + log tail
/kaizen:hygiene check                    # on-demand check (same logic)
/kaizen:hygiene fix                      # on-demand safe cleanups
/kaizen:daemon uninstall                 # remove cron entry
```

### Why minor bump (1.4.x → 1.5.0)

New surface area (2 commands, 2 scripts, 2 wrappers, ~600 LOC), new cron integration, new daemon state schema. No breaking changes — `/kaizen:install`, `/kaizen:update`, `/kaizen:gate` etc. all behave identically.

## [1.4.4] — 2026-05-11

### Added — conditional auto-reload on `/kaizen:update`

`/kaizen:update` now triggers `/reload-plugins` automatically when (and only when) something actually changed. Closes the last manual step in the maintenance flow.

**How it works**

`scripts/update.sh` now ends with one of two machine-parseable marker lines:

- `kaizen-update: needs-reload (changes applied)` — a pull landed OR the cache moved.
- `kaizen-update: no-op (already current)` — nothing changed.

`commands/update.md` reads the marker after the bash block and instructs Claude to emit the literal text `/reload-plugins` only on `needs-reload`. Claude Code's UI then triggers the built-in reload. No reload spam on idempotent re-runs.

**Why this isn't a hook**

`/reload-plugins` is a Claude Code built-in slash command, not a shell command. Hooks can't trigger it directly (no `triggerSlashCommand` field in hook output JSON), and bash scripts have no access to the harness. The slash-command-MD-instructs-Claude-to-emit-slash-text pattern is the cleanest workable path — and it costs nothing to fall back to: if Claude doesn't emit the slash, the user can still type `/reload-plugins` themselves.

**Shell behaviour unchanged**

`kaizen update` from a regular shell prints the same marker lines (informational only — no reload-plugins concept outside Claude Code). Use the marker as an exit signal in scripts: `kaizen update | tail -1 | grep -q needs-reload && echo "would reload"`.

**Maintenance loop is now one step**

Before v1.4.4:
```
/kaizen:update
/reload-plugins      # manual
```

After v1.4.4:
```
/kaizen:update       # auto-reloads if anything changed
```

## [1.4.3] — 2026-05-11

### Added — single-command maintenance flow

`/kaizen:update` (and `kaizen-update` / `kaizen update` from the shell) collapses the manual `cd marketplace + git fetch + git pull + /kaizen:refresh-cache + /reload-plugins` dance into one command.

**`scripts/update.sh`** — handles the full flow:

1. `git ls-remote origin master` — peek at upstream HEAD without fetching (network-light).
2. Compare local HEAD vs remote, report "up to date" or "N commits behind".
3. If behind: `git pull --ff-only` (refuses non-fast-forward — surfaces conflicts instead of blindly merging).
4. Run `refresh-cache.sh` to sync the version-named cache slot (always, so local hand-edits also flush).
5. Print "/reload-plugins to activate".

**Subcommands**:

| arg | effect | exit |
|---|---|---|
| (none) or `pull` | full flow | 0 on success |
| `check` | read-only status, no mutation | 0 if up-to-date, 1 if behind (scriptable in CI) |
| `prune` | drop old cache versions, keep newest N (default 2) | 0 |
| `path` | print marketplace dir | 0 |

**`bin/kaizen-update`** — shell wrapper, symlinked into `~/.local/bin/` by `/kaizen:install`. Available as `kaizen update` (multiplexer) or `kaizen-update` (direct).

**Env overrides**:

- `KAIZEN_MARKETPLACE` — override marketplace dir
- `KAIZEN_KEEP_VERSIONS` — prune retention (default 2)

### Why

Before:

```
cd ~/.claude/local-marketplaces/kaizen-md
git fetch origin
git log HEAD..origin/master
git pull origin master
/kaizen:refresh-cache
/reload-plugins
```

After:

```
/kaizen:update
/reload-plugins
```

Plus `--ff-only` safety, automatic cache refresh even on local edits, and a `prune` subcommand to clean up stale version dirs (the v1.1.0 / v1.1.6 / v1.4.0 / v1.4.1 / v1.4.2 stack would normally grow forever).

## [1.4.2] — 2026-05-11

### Added — zero-config shell access + cache refresh

**`bin/` directory** — 8 thin shell wrappers exec'd from `~/.local/bin/`:

- `kaizen` (multiplexer: `kaizen flow .`, `kaizen docs scan`, etc.)
- `kaizen-flow`, `kaizen-docs`, `kaizen-backlog`, `kaizen-cache`, `kaizen-context`, `kaizen-inbox`, `kaizen-rules`

Each wrapper is ~5 LOC, self-locating via `python3 os.path.realpath` so symlinked installs resolve back to the real plugin root. No `source kaizen-env.sh` needed.

**`scripts/install.sh` auto-symlinks `bin/*` → `~/.local/bin/`** during `/kaizen:install`. Idempotent. Skips files that already exist and aren't symlinks (no clobber). Opt-out: `KAIZEN_NO_BIN=1`. Warns if `~/.local/bin` isn't on `$PATH`.

**`/kaizen:refresh-cache`** — forces Claude Code's plugin cache to match the local-marketplace source. Solves the gap where `/plugin update kaizen@kaizen-md` doesn't reliably refresh local-marketplace plugins on version bump (`/reload-plugins` then serves stale content). Reads version from source `plugin.json`, rsyncs (or `cp -a` fallback) over the version-named cache slot.

Subcommands: (none = refresh) / `--dry-run` / `--force`.

### Zero-config wins

| Before | After |
|---|---|
| `python3 ${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/flow_demo.py .` (failed outside CC) | `kaizen flow .` |
| `source <path>/kaizen-env.sh && kaizen-flow .` | `kaizen-flow .` (after `/kaizen:install`) |
| `/plugin update + /reload-plugins` + hope cache refreshed | `/kaizen:refresh-cache + /reload-plugins` deterministic |

## [1.4.1] — 2026-05-11

### Added — shell env for interactive use

`${CLAUDE_PLUGIN_ROOT}` is auto-set inside Claude Code (hooks/skills) but undefined in your regular shell. v1.4.0 docs gave commands like `python3 ${CLAUDE_PLUGIN_ROOT}/skills/...` that collapsed to `/skills/...` in bash/zsh and failed.

- **`scripts/kaizen-env.sh`** — sourceable env exporter. Sets `KAIZEN_ROOT`, `KAIZEN_SCRIPTS`, prepends scripts dir to `$PATH`, defines aliases (`kaizen-flow`, `kaizen-docs`, `kaizen-backlog`, `kaizen-cache`, `kaizen-context`, `kaizen-inbox`, `kaizen-rules`). Resolves its own location via `realpath`/`python3 os.path.realpath` so symlinked installs work.
- **`/kaizen:env`** slash command — `print | install | install-zsh | path | uninstall`. `install` appends `source <path>/kaizen-env.sh` to `~/.bashrc` (or `~/.zshrc`) with idempotence + timestamped backup on uninstall.

### Fixed

- **`/kaizen:flow` was stale** — description said "3-node pipeline (ReadBacklog → Analyze → Report)" but v1.4.0 shipped the 4-node async demo with `asyncio.gather` fan-out. Updated description + body to match real behaviour, including the shodan-realistic sample output (26 packages, 236k LOC, 1.14 s parallel scan).

## [1.4.0] — 2026-05-11

### Added — docs generator, async demo, non-blocking inbox

Four features compose as v1.4.0:

**1. Generic workspace docs generator** (`scripts/docs_gen.py` + `/kaizen:docs`)

Ports shodan's `cargo xtask docs --json` to a language-agnostic Python tool.
Detects packages by manifest marker:

| Marker | Language |
|---|---|
| `Cargo.toml` | rust |
| `package.json` | js |
| `go.mod` | go |
| `pyproject.toml` | python |

Per package emits `<name>.md` + `<name>.json` (schema `kaizen.docs` v1) with: name, path, language, version (workspace-inherited coerced to `"workspace"`), LOC src/test split, files src/test split, deps + dev_deps, public_api counts (fn/struct/trait/enum/class/...) + up to 30 sample names. Skips `target/`, `node_modules/`, `vendor/`, etc. Stdlib-only (`tomllib` on 3.11+, regex fallback for older Python). Tested on shodan: 24 crates scanned, 4632 LOC in `shodan-core`, 164 pub fns, 50 structs, 27 traits, 34 enums.

CLI: `detect | scan | one`.

**2. Async Node+Flow demo** (`scripts/flow_demo.py` rewrite)

Replaces the sync backlog-summary toy with a real async pipeline:

```
ReadBacklog → DetectPackages → GenerateDocs → WriteReport
                               (fan-out via       (terminal)
                                asyncio.gather)
```

Highlights:
- Vendored `AsyncNode` + `AsyncFlow` (~40 LOC) — zero runtime deps, shape mirrors PocketFlow exactly. `pip install pocketflow` is a one-line swap.
- Three-phase nodes: `prep_async` → `exec_async` → `post_async`.
- `GenerateDocs` fans out N packages → N concurrent tasks via `asyncio.gather`, with `asyncio.to_thread` pushing blocking file I/O off the event loop.
- Per-node timing in `store['_timing']` for the JSON summary.

Real-world: 24 packages scanned on shodan in 1.36s wall-clock (1.3s spent concurrently in `GenerateDocs`).

**3. Non-blocking message inbox** (`scripts/inbox.py` + 2 hooks + `/kaizen:inbox`)

Closes the "Claude is busy" gap. When the harness is mid-tool-call and the user types a follow-up, that message normally only reaches Claude when the WHOLE current tool sequence finishes. The inbox surfaces pending user input on the very next tool boundary instead.

- **UserPromptSubmit hook** (`hooks/userprompt-inbox.sh`) captures every prompt to `~/.claude/kaizen-inbox/<ts>.json`. Non-blocking — exits 0 silently regardless of capture outcome.
- **PostToolUse hook** (`hooks/posttooluse-drain-inbox.sh`, matcher `"*"`) drains pending messages, wraps in:
  ```json
  {"hookSpecificOutput":
    {"hookEventName": "PostToolUse",
     "additionalContext": "USER MESSAGE(S) RECEIVED WHILE BUSY: ..."}}
  ```
- **`inbox.py`** CLI: `capture | list | peek | drain | clear | stats`. Drained messages stay on disk as audit trail (cleared via `/kaizen:inbox clear`).

Discipline: at-most-once per submit. Drained messages flip `drained: true` + `drained_at: <iso>` so no message re-surfaces. If python3 is missing or the hook errors, your prompt still reaches Claude through the harness's normal path.

**4. Tests + plugin-pitfalls #14**

- `tests/test_docs_gen.py` (12 tests) — language detection, version coerce, LOC + test-file detection, parsers (Rust/JS/Go), public API regex, end-to-end scan.
- `tests/test_inbox.py` (10 tests) — capture, collision-resistant filenames, list filtering, drain + peek semantics, clear, stats.
- **plugin-pitfalls #14**: `additionalContext` requires `hookSpecificOutput` envelope with `hookEventName` matching the firing event. Bare strings don't inject. Multiple matcher entries vs additional hooks within a single matcher behave subtly differently.

22 new tests; full suite 70/70.

## [1.3.0] — 2026-05-11

### Added — agent fleet + intelligent infrastructure

Six features compose as v1.3.0:

**1. Agent fleet** (`agents/`, auto-discovered)

- **`kaizen-reviewer`** — audits staged diff vs the 10 gate rules + brain-sourced severity overrides; returns `{verdict: green|yellow|red, checks, diff_sha1, rationale}`.
- **`kaizen-backlog-curator`** — mines session JSONL for backlog candidates with probe + verify fields; dedups against existing backlog + brain Notes; never writes itself.
- **`kaizen-debt-auditor`** — scans codebase against onion-DDD + 8 coding-skills + depth invariants; ranks findings by `severity × ease`.

All three declare worktree-isolation contract in their bodies (caller passes `isolation: "worktree"`).

**2. Plugin permissions** (`plugin.json.permissions.allow`)

Pre-authorizes all `${CLAUDE_PLUGIN_ROOT}` scripts (Python/bash/node), reads of `.kaizen/**` / `.workflow/**` / `.kaizen.toml`, writes of `.kaizen/cache/**`. Brain reads (`~/.claude/brain/**`) still prompt — intentional.

**3. Statusline + context-window awareness**

- `scripts/statusline.sh` — one-line bar: `🟢 95k/200k (47%) │ ⚪ 5 next up │ 🟢 gate`. Renders <50 ms.
- `scripts/context.py` — resolve tokens from `CLAUDE_CONTEXT_TOKENS` env / stdin JSON; zones green/yellow/red/unknown.
- Gate **Check #12** — advisory red-zone warn; never blocks.

**4. Hash-keyed cache**

- `scripts/cache.py` — per-repo JSON cache at `<repo>/.kaizen/cache/` (gitignored). SHA1 keys, no TTL.
- Gate **Check #1 wired** — compile barrier caches green verdicts keyed by `(cmd, sha1(staged-diff))`. Failed runs NOT cached.
- Agents document cache keys in their invocation contracts.

**5. New slash commands**

- `/kaizen:cache`, `/kaizen:context`, `/kaizen:statusline`

### Tests

- `tests/test_cache.py` (8 tests), `tests/test_context.py` (13 tests), `tests/test_agents_schema.py` (5 tests). 34/34 new tests pass; full suite green.

### Plugin-pitfalls (#11–#13)

- **#11** plugin `permissions` block schema is sparsely documented — pattern grammar, `${CLAUDE_PLUGIN_ROOT}` substitution, `deny` precedence all need empirical verification.
- **#12** agent `isolation` is per-invocation, not per-definition — declare the contract in the agent body; callers must pass `isolation: "worktree"`.
- **#13** statusline scripts have <50 ms render budget — no network / LLM / slow git; only file reads + stdin parse.

## [1.2.0] — 2026-05-11

### Added — brain-sourced rules + behaviour config

Three new rule types stored as Remember Notes (frontmatter `kaizen:` block). Plugin scripts read at gate-time; survives across projects + sessions.

- **`deletion-allow`** — whitelist `path_glob` for `git rm` (skips pre-deletion belief scan for matching paths)
- **`check-severity`** — override any of the 10 gate checks: `skip` / `warn` / `block`
- **`custom-pattern`** — run a regex over staged diff; `warn` or `block` on hit

New skill: **`kaizen:behaviour-config`** (35th bundled) — full schema docs, all 3 rule types with examples + Iron Laws + authoring workflow.

New CLI: **`scripts/rules.py`** — `list`, `show`, `deletion-allowed <path>`, `severity <check>`, `custom-patterns`, `validate`, `template <type>`.

New slash command: **`/kaizen:rule`** wraps the CLI.

Gate integrations:
- Check #5 (pre-deletion gate) — if EVERY staged deletion matches a `deletion-allow` rule, the belief scan is skipped (no `KAIZEN_ALLOW_DELETE=1` needed).
- Check #7 (paired-test) — consults `check-severity` rule for `check_id: paired-test`; can be set to `skip` to silence.
- Check #11 (NEW) — runs `custom-pattern` rules over `git diff --cached`; emits warn or block per `pattern_action`.

### Fixed

- **`_SCRIPT_REAL_DIR` unbound variable** in `pre-commit.sh` when Check #5 (pre-deletion) didn't fire — gotcha #7 from plugin-pitfalls (set -u + fallback branches). Same lesson as install.sh (v1.1.6) and doctor.sh (v1.1.3). Third occurrence — hoist policy: any variable referenced by multiple checks gets defined once at script top.

## [1.1.6] — 2026-05-11

### Fixed

- **`install.sh` unbound-variable crash on re-install** — when `.kaizen.toml` already exists (re-install path), `DEFAULT_BACKLOG` was never set, but the seed-backlog block referenced it. `set -uo pipefail` then aborted with `DEFAULT_BACKLOG: unbound variable` (after the symlink + hooksPath + gitignore steps had already succeeded). This is **gotcha #7** from `plugin-pitfalls` — meta: the very skill that documents this failure mode caught the plugin's own version of it.
- Fix: resolve `backlog_path` from the live `.kaizen.toml` via grep (with `${DEFAULT_BACKLOG:-backlog.md}` as fallback when neither config nor default is set).

## [1.1.5] — 2026-05-11

### Fixed

- **Documentation drifts in `skills/kaizen/SKILL.md`** (surfaced by re-reading the loaded skill in-session):
  - Bundled-skill count: 32 → **34** (now reflects `publishing` + `plugin-pitfalls` added in 1.1.0/1.1.3).
  - Gate header: "8-item" → **"10-check"** pre-commit gate.
  - PART 3 table extended with the 2 newer checks:
    - Check #9 — committed-secret detection (regex for AWS / GitHub / OpenAI / Slack / Google API keys + JWTs + private keys; bypass `KAIZEN_ALLOW_SECRET=1`).
    - Check #10 — backlog `.md` drift vs `.json` (runs `backlog.py verify`).
  - `.kaizen.toml` example `backlog_path` lowercased to `.workflow/backlog.md` (matches the install-default + the `state.json` / `snapshot.md` / `progress.md` lowercase convention).

## [1.1.4] — 2026-05-11

### Fixed

- **`/kaizen:help` → `/kaizen:menu`** — eats own dogfood for gotcha #4 (built-in shadowing). The `help` command name shadowed Claude Code's `/help` built-in. Renamed to `menu`.
- **plugin-pitfalls lint script** scoped to `.sh`/`.py`/`hooks/` files for gotcha #6 (was matching documentation prose mentioning `readlink -f` in README/CHANGELOG/SKILL.md). Also fixed exit-code logic (was printing "BUG #6 ... All checks passed" simultaneously).

## [1.1.3] — 2026-05-11

### Added

- **`plugin-pitfalls` skill** (34th bundled) — catalogues 10 real failure modes encountered during the v1.0 → v1.1.2 release cycle. Each entry has symptom (what the user sees), cause (why the system rejects it), fix (the concrete repair), and prevention (the lint check that would have caught it).

The 10 gotchas:
1. `hooks.json` must be wrapped in top-level `{"hooks": {...}}` record
2. Slash commands evaluate ALL fenced bash blocks, not just the matching one
3. `/plugin update` no-ops without a `version:` bump in plugin.json
4. Plugin `name: doctor` (etc.) shadows Claude Code built-ins
5. SSH key vs `gh` CLI auth mismatch causes "Repository not found"
6. `readlink -f` and `find -printf` are GNU-only — break on macOS BSD
7. `set -uo pipefail` aborts on unbound vars in fallback branches
8. Python heredoc inside bash needs `<<'PY'` (quoted EOF) for escapes
9. Skill name collisions: loose `~/.claude/skills/X` + bundled `<plugin>/skills/X` both appear
10. `gh repo create --remote=origin` fails when origin already exists

Includes a pre-publish lint script covering all 10. Triggers on symptom phrases ("Hook load failed", "Repository not found", "expected record received undefined", etc.) so the skill activates when a gotcha symptom appears in a session.

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
