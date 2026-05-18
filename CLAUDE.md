# CLAUDE.md

This file is the **project orientation handle** for kaizen-md. Durable
rules live in brain (`~/.claude/.kaizen/brain/Notes/`) — see
`[[Notes/pref-claude-md-is-rulebook-not-state]]`. Per-project orientation
+ runnable surface + SSOT pointers live here.

## What this repo is

`kaizen-md` is a **Claude Code plugin marketplace**. `.claude-plugin/marketplace.json`
bundles two things:

- **`plugins/kaizen/`** — the only plugin-original code; this is where ~all
  development happens. A self-contained Claude Code plugin: a git pre-commit
  gate, a JSON-sourced backlog, a large set of skills, MCP servers, lifecycle
  hooks, `bin/` wrappers, and a Python `unittest` suite.
- **`plugins/*-lsp/`** — LSP plugins redistributed verbatim from
  `claude-plugins-official`. Do not edit these.

There is no build step — the plugin is shell scripts, Python scripts, and
markdown. "Building" means running the test pipeline.

## Commands

All commands run from the repo root unless noted.

```bash
# Full Python unit suite (unified harness; auto-style detection, parallel)
kaizen-tests

# Single test file
kaizen-tests --pattern "test_brain*"

# Bench — find slow files
kaizen-tests bench --top-n 10

# End-to-end smoke pipeline (TAP-style, sandboxes in /tmp/gwtest-*)
bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh

# Plugin health diagnostic
bash plugins/kaizen/skills/workflow/scripts/health.sh

# Install the plugin into a project (dogfooding — sets local core.hooksPath)
bash plugins/kaizen/skills/workflow/scripts/install.sh

# Lint
ruff check plugins/kaizen/skills/workflow/scripts/
```

CI (`.github/workflows/test.yml`, Ubuntu + macOS) runs: `bash -n` on every
shell script, `ast.parse` on every Python script, JSON-validity on every
manifest, and a **GNU-only-utility ban** (see
`[[Notes/pref-cross-platform-no-gnu-only]]`).

## Editing rules — read before touching plugin code

Full rule body in `[[Notes/pref-kaizen-plugin-dev]]`. Key points:

- **Canonical edit path** is `~/workspace/kaizen-md/`. Don't edit through
  the `~/.claude/local-marketplaces/kaizen-md/` symlink.
- **Load `Skill(plugin-development)` first** before any plugin-original
  change. Run
  `python3 plugins/kaizen/skills/plugin-development/scripts/validate.py --staged`
  before staging.
- **Never edit vendored skills** (hard rule). The vendored list is in
  `skills/iron-laws/domain/iron-laws.yaml::no-modify-vendored` and
  `ATTRIBUTIONS.md`.

## Dispatching subagents

Safe defaults in `[[Notes/pref-subagent-dispatch-safe-defaults]]`. TL;DR:
use `kaizen:kaizen-implementer` for multi-phase TDD work in isolated
worktrees (its tool list blocks destructive git ops); `general-purpose`
needs `touch ~/.claude/.kaizen/strict` for multi-commit work.

## Architecture

### Plugin eats its own dogfood

Committing in this repo fires the plugin's own pre-commit + commit-msg
gate (installed via local `core.hooksPath = .kaizen/hooks`).
Consequences for any commit:

- **Conventional Commits** subject required (`feat(scope): | fix: | ...`).
- A **structural change** must ship a row in `.kaizen/workflow/progress.md`
  in the same commit.
- `git rm` is blocked unless `KAIZEN_ALLOW_DELETE=1` is set.
- CLAUDE.md / README.md must not contain commit SHAs, dates, or LOC counts
  (see `[[Notes/pref-claude-md-is-rulebook-not-state]]`).
- Micro work tracked in `.kaizen/workflow/backlog.json` via `backlog.py`.
  Work ≥16 files → a `plans/<date>-<slug>.md` plan file.

### Canonical feature shape

Source-of-truth: `skills/plugin-development/domain/feature-shape.yaml`
(the yaml wins). Each feature lands files across the slots defined
there: skill body / domain config / private core (`_<feature>.py`) /
public CLI (`<feature>.py`) / indexer / MCP server / hooks / commands /
bin wrappers / tests. See `[[Notes/pref-kaizen-plugin-dev]]`.

### Onion-DDD layout

Larger skills are layered: `domain/` (pure yaml + JSON Schemas) →
`application/` (loaders + codegen) → `scripts/` (adapters: shell + MCP
wrappers) → `references/` (generated docs — regenerate via
`application/codegen.py`). Inward-only deps. See
`[[Notes/pref-onion-architecture-strict]]`.

### Iron laws (hard = commit-blocking)

Source-of-truth: `skills/iron-laws/domain/iron-laws.yaml`. Inspect via
`kaizen-iron-laws list` or `kaizen-iron-laws check --staged`. Hard laws
include `bin-wrapper-per-cli`, `plugin-manifest-permissions`,
`hook-bypass-knob`, `sandbox-tests`.

### Cross-platform

Linux GNU **and** macOS BSD must both work. See
`[[Notes/pref-cross-platform-no-gnu-only]]`.

### `.kaizen/workflow/` namespace

Per-file ownership: `backlog.{json,md}` → the plugin;
`state.json` + `snapshot.md` → the `/workflow` routing engine;
`progress.md` → architecture log.

### Configuration & paths — the centralized trio

| File | Layer | What it owns |
|---|---|---|
| `skills/workflow/scripts/config.py`  | **Plugin defaults** + per-project TOML parser | `PLUGIN ▸ DEFAULTS` constants + `.kaizen.toml` reader |
| `skills/workflow/scripts/_paths.py`  | **Path SSOT (Python)** | every `KAIZEN_*_DIR` resolver |
| `skills/workflow/scripts/_paths.sh`  | **Path SSOT (shell mirror)** | bash-source-able variants |

**Resolution order** (low → high precedence):
1. `config.py::PLUGIN_DEFAULTS`
2. `_paths.{py,sh}` env-overridable paths
3. `<repo>/.kaizen.toml`

**Inspect:**

```bash
kaizen-config --defaults                # plugin-wide defaults
kaizen-config <key>                     # one resolved value
source plugins/kaizen/skills/workflow/scripts/_paths.sh && env | grep KAIZEN_
```

Common env knobs (full list in `_paths.sh`): `KAIZEN_DIR`,
`KAIZEN_HANDOFF_DIR`, `KAIZEN_BACKUP_DIR`, `KAIZEN_DXM_DIR`,
`KAIZEN_INBOX_DIR`, `KAIZEN_<FEATURE>_DISABLE`.

When prose and these files disagree, **code wins** — the trio is the SSOT.

### Domain organization + consolidation patterns

See `[[Notes/pref-kaizen-consolidation-patterns]]` for the rules. Current
cluster snapshot (drifts) at `.kaizen/superpowers/architecture-snapshot.md`.

When adding a feature: pick one of the 4 canonical shapes
(`lens-manifest` / `decision-rubric` / `plain-config` / `rule-catalog`)
under `skills/<feature>/domain/`. Audit via `kaizen-schema-coverage`.

### Coverage axes

See `[[Notes/pref-coverage-axis-naming]]`. Current axes: code-to-test /
schema / name-quality / frontmatter. Name new axes `<thing>-coverage` and
register as their own `SUB_GATES` key in `kaizen-gatekeeper`.

### JSONL-indexed deliverables

See `[[Notes/pref-jsonl-indexed-deliverables]]`. For any output ≥30
structured entries (plans, brainstorms, audit results), ship paired
`.md` + `.jsonl` so consumers can `jq` the slice without whole-file Read.

### Audit surface (one-command sanity)

```bash
kaizen-gatekeeper check --all   # 7 sub-gates aggregated (one verdict)
kaizen-token-bloat scan         # bloat axis
kaizen-coverage gaps            # code-to-test-coverage axis
kaizen-schema-coverage gaps     # schema-coverage axis
kaizen-name-quality gaps        # name-quality axis
```

All also fire automatically — SessionEnd refreshes the token-bloat cache,
`kaizen-gatekeeper` runs in the pre-commit gate, `kaizen-schema-coverage`
surfaces via gatekeeper.

## What does NOT live here

Per `[[Notes/pref-claude-md-is-rulebook-not-state]]`:

- Long-form rule bodies — brain Note + link.
- Cluster snapshots / counts that drift fast — see
  `.kaizen/superpowers/architecture-snapshot.md`.
- Volatile data (SHAs, dates, LOC counts) — `git notes` / `progress.md` /
  `CHANGELOG.md` / self-checking commands.
