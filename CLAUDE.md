# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
# Full Python unit suite — run from plugins/kaizen/
cd plugins/kaizen && python3 -m unittest discover -s tests -p "test_*.py"

# A single test file (run from plugins/kaizen/; each file passes standalone)
cd plugins/kaizen && python3 -m unittest tests.test_backlog

# End-to-end smoke pipeline (TAP-style, sandboxes in /tmp/gwtest-*) — expect all green
bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh

# Plugin health diagnostic
bash plugins/kaizen/skills/workflow/scripts/health.sh

# Install the plugin into a project (dogfooding — sets local core.hooksPath)
bash plugins/kaizen/skills/workflow/scripts/install.sh

# Lint (ruff is used locally; no repo ruff config — defaults apply)
ruff check plugins/kaizen/skills/workflow/scripts/
```

CI (`.github/workflows/test.yml`, Ubuntu + macOS) runs: `bash -n` on every
shell script, `ast.parse` on every Python script, JSON-validity on every
manifest, and a **GNU-only-utility ban** (`readlink -f`, `find -printf`
fail CI — see Cross-platform below).

## Editing rules — read before touching plugin code

- **Canonical path.** Edit at `~/workspace/kaizen-md/`. `~/.claude/local-marketplaces/kaizen-md/`
  is a symlink to it — editing through the symlink confuses git/IDE/path tooling.
- **Load the `plugin-development` skill first** for any change to plugin-original
  code. It encodes the canonical feature shape, the iron laws, and the wiring
  checklist. Validate a change with
  `python3 plugins/kaizen/skills/plugin-development/scripts/validate.py --staged`.
- **Never edit vendored skills** (hard rule). Many skills under
  `plugins/kaizen/skills/` are vendored from upstream projects (coding-skills ©
  JordanCoin, superpowers © obra, remember © remember-md). The exact list is in
  `skills/iron-laws/domain/iron-laws.yaml::no-modify-vendored` and
  `ATTRIBUTIONS.md`. To change one: patch upstream, then `bundle-refresh` (see
  `plugins/kaizen/CONTRIBUTING.md`). Plugin-original code is `skills/workflow/`,
  the kaizen-authored `skills/<feature>/`, and `scripts/ commands/ hooks/ bin/`.

## Architecture

### The plugin eats its own dogfood

Committing in this repo fires `plugins/kaizen`'s own pre-commit + commit-msg
gate (installed via local `core.hooksPath = .kaizen/hooks`). Consequences for
any commit here:

- **Conventional Commits** subject required (`feat(scope): | fix: | refactor: | docs: | chore: | test: ...`).
- A **structural change** (new script, new module, manifest edit) must ship a
  row in `.kaizen/workflow/progress.md` (the architecture log) **in the same commit**.
- `git rm` is blocked unless `KAIZEN_ALLOW_DELETE=1` is set for that commit.
- CLAUDE.md / README.md must not contain commit SHAs, dates, or LOC counts
  (those live in `CHANGELOG.md` / `git log` / `progress.md`).
- Micro work is tracked in `.kaizen/workflow/backlog.json` via `backlog.py`
  (`add`/`start`/`tick`/`park`) — never hand-edit the generated `backlog.md`.
  Work ≥16 files / cross-cutting → a `plans/<date>-<slug>.md` plan file with a
  `## Status` block.

### The canonical feature shape

Every plugin-original *feature* lands files into a fixed set of slots, defined
in `skills/plugin-development/domain/feature-shape.yaml` (that file is the
source of truth — its own header says "11-slot" but it currently defines 13;
trust the slot list, not the label):

| Slot | Path | When |
|---|---|---|
| skill body | `skills/<feature>/SKILL.md` | always |
| domain config | `skills/<feature>/domain/*.yaml` | feature routes/classifies |
| artifact schemas | `skills/<feature>/domain/schemas/*.schema.json` | feature writes structured files |
| skill-scoped tooling | `skills/<feature>/scripts/*.py` | skill-private validators/generators |
| private core | `skills/workflow/scripts/_<feature>.py` | feature has a core/CLI split |
| public CLI | `skills/workflow/scripts/<feature>.py` | feature has a CLI |
| indexer | `skills/workflow/scripts/<feature>_index.py` | feature needs SQLite search |
| specialized flows | `skills/workflow/scripts/<feature>_<op>.py` | feature has 2+ orthogonal ops |
| MCP server | `skills/workflow/scripts/<feature>_mcp.py` | feature exposes MCP tools |
| hook scripts | `hooks/claude/<feature>-*.sh` | feature uses lifecycle events |
| slash command | `commands/<feature>.md` | feature has a CLI |
| bin wrapper | `bin/kaizen-<feature>*` | feature has a CLI |
| tests | `tests/test_<feature>*.py` | feature has a core/CLI split |

Note **most feature backing code is flat in `skills/workflow/scripts/`**
regardless of which skill owns it — `_<x>.py` = private shared helpers
(`_sqlite`, `_embed`, `_chunk`, `_search`, `_indexer_cli`, and `flow.py` — the
`AsyncNode`/`AsyncFlow` primitives); `<feature>.py` = CLIs; `<feature>_mcp.py` =
MCP servers (each a PEP-723 `uv run --script` shebang script with an inline dep
block); `<feature>_index.py` = SQLite + semantic-search indexers. The exception
is **skill-private tooling**, which lives at `skills/<feature>/scripts/` (e.g.
`plugin-development/scripts/validate.py`, `karpathy/scripts/*.py`).

### Onion-DDD layout inside skills

Larger skills (most visibly `skills/workflow/`) are layered: `domain/` (pure
yaml data + JSON Schemas, no behavior) → `application/` (loaders + codegen) →
`scripts/` (adapters: shell + MCP wrappers) → `references/` (generated docs —
do not hand-edit; regenerate via `application/codegen.py`). Dependency arrows
point inward only. New rules go in `domain/`, new behavior in `application/`,
new I/O in `scripts/`.

### Iron laws (hard = commit-blocking)

Full spec in `skills/iron-laws/domain/iron-laws.yaml`. The hard ones:

- **bin-wrapper-per-cli** — every `skills/workflow/scripts/*.py` with an
  `argparse` main gets its own `bin/kaizen-*` wrapper **in the same commit**
  (`/kaizen:install` symlinks `bin/` into `~/.local/bin/`; a missing wrapper =
  "command not found").
- **plugin-manifest-permissions** — a new script or hook ships its matching
  `plugin.json::permissions.allow` entry in the same commit.
- **hook-bypass-knob** — every `hooks/claude/*.sh` reads `KAIZEN_<FEATURE>_DISABLE`
  early and exits 0 when set; and fires `_trace.sh` so its run is observable.
- **sandbox-tests** — tests isolate via `KAIZEN_<X>_PATH=<tmp>` env vars; never
  touch the real `~/.claude/`.

Soft laws worth knowing: feature routing/taxonomies belong in `domain/*.yaml`,
not hardcoded Python; heavy deps (`torch`, `transformers`, `tree-sitter`) must
lazy-load with `is_available()` + graceful fallback so the default install
stays light; multi-step async work uses `flow.py`'s `AsyncNode`/`AsyncFlow`.

### Cross-platform

Linux GNU **and** macOS BSD must both work. `python3` is the only hard runtime
dep beyond `bash` + `git`. Avoid GNU-only utilities: `readlink -f` and
`find -printf` fail CI outright; `sed -i` without `''` is also banned (a
CONTRIBUTING.md rule). Use the helpers in `skills/workflow/scripts/`
(`_plugin_root.sh`, `_paths.sh`, etc.) instead.

### `.kaizen/workflow/` namespace

Per-file ownership (no cross-writes): `backlog.{json,md}` → the kaizen plugin;
`state.json` + `snapshot.md` → the `/workflow` routing engine; `progress.md` →
the architecture log (project convention).

### Configuration & paths — the centralized trio

| File | Layer | What it owns |
|---|---|---|
| `skills/workflow/scripts/config.py`  | **Plugin defaults** + per-project TOML parser | `PLUGIN ▸ DEFAULTS` constants (embedding model, dims, size caps) + `.kaizen.toml` reader |
| `skills/workflow/scripts/_paths.py`  | **Path SSOT (Python)** | every `KAIZEN_*_DIR` resolver — the `~/.claude/.kaizen/` layout |
| `skills/workflow/scripts/_paths.sh`  | **Path SSOT (shell mirror)** | bash-source-able variants of the same KAIZEN_*_DIR vars |

**Resolution order** (low → high precedence):
1. `config.py::PLUGIN_DEFAULTS` (shipped defaults)
2. `_paths.{py,sh}` env-overridable paths (`KAIZEN_*` env vars)
3. `<repo>/.kaizen.toml` (per-project key=value)

**Inspect at runtime:**

```bash
kaizen-config --defaults                # plugin-wide defaults
kaizen-config <key>                     # one resolved value
source plugins/kaizen/skills/workflow/scripts/_paths.sh && env | grep KAIZEN_
```

**Common env knobs** (full list in `_paths.sh`):
- `KAIZEN_DIR` — user-global root (default `~/.claude/.kaizen/`)
- `KAIZEN_HANDOFF_DIR` — handoff YAMLs (default `~/.claude/handoff/`, separate from `.kaizen/` because it's user-facing)
- `KAIZEN_BACKUP_DIR`, `KAIZEN_DXM_DIR`, `KAIZEN_INBOX_DIR`, …
- `KAIZEN_<FEATURE>_DISABLE` — per-feature bypass (every hook honors this)

When prose and these files disagree, **code wins** — the trio is the SSOT.
