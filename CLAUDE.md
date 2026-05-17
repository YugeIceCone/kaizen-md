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

### Domain organization — the 9 surface clusters

The plugin has grown large (90 skills, 66 bins, 51 slash commands, 35 hooks,
24 MCPs). New surface lands in **one** of these 9 domain clusters. Use the
matching consolidated-CLI-parent when present; only mint a top-level bin when
no parent fits.

| Domain | Purpose | Aggregator | Members (representative) |
|---|---|---|---|
| **audit/quality** | gate the diff; surface bloat / shape gaps / coverage | **`kaizen-gatekeeper`** aggregates 7 sub-gates | iron-laws, etu, karpathy, validator, token-bloat, coverage, schema-coverage |
| **observability** | trace lifetime, dxm live mirror, context window | (no parent — each is a distinct concern) | trace, dxm, metrics, observe, context, statusline |
| **brain/memory** | Second Brain (Persona / PARA / Notes) | **`kaizen-brain`** multi-verb (audit / evolve / index / promote / migrate) | brain, remember, reflect, evolve, memory-state |
| **workflow** | routine engines + backlog + handoff | (kept separate — different runtimes; see note below) | workflow, loop, flow, backlog, handoff, auto-handoff, roadmap |
| **plugin-meta** | install / update / hygiene / cache | (no parent yet) | bootstrap, cache, daemon, enable-all, hygiene, manifests, migrate, surface, update, watch |
| **discovery/search** | semantic indexes + grep wrappers | per-feature (each `<feature>-index` + matching MCP server) | onboard, knowledge, loc, drift, scrape, models, claude-docs |
| **intent/session** | live phrase-matching + session mode + skill-suggest | (each distinct, no aggregator) | intent, session-mode, skill-suggest |
| **writing/io** | atomic file writers + shim | `_atomic` is the shared helper | write, shim |
| **dev-aids** | scratch tools + rubric / rules CLI | per-tool | rubric, rules, scratch, browser, code-lift, test, docs |

**Workflow domain — why workflow / loop / flow are intentionally three things:**

| Bin | Runtime | Cadence | State file | Driver |
|---|---|---|---|---|
| `kaizen-workflow` | multi-stage routine (audit / build-feature / fix-bug / refactor / migrate / harden / debug-with-pdb / mcp-build / minimalist / spec-driven / onion-tdd-strict / kaizen-default) | **per-stage**: agent calls `workflow advance` to move to the next stage; each stage has its own gate | `.kaizen/workflow/state.json` (current stage, completed list) + `snapshot.md` | agent-orchestrated; user picks routine + runs `/workflow <routine>` |
| `kaizen-loop` | self-correcting iterative refinement (ralph-loop pattern) | **per-iteration**: every pass verifies → re-attempts until convergence or stop-condition | `.kaizen/loop.state.md` (active loop ledger; frontmatter + JSON body) | hook-fired (`Stop-ralph-loop` event) or agent-driven via `/kaizen:loop` |
| `kaizen-flow` | Node+Flow primitives — the actual `AsyncNode` / `AsyncFlow` runtime (`skills/workflow/scripts/flow.py`) | **per-graph-execution**: a single flow runs once to completion | none (graph is built + executed in-process) | imported by every multi-step Python module (indexers, gate, brain promote, etc.) |

Workflow drives the discipline (stage gates); loop drives the convergence
(retry until verified); flow is the shared substrate both build on. Same
family, three independent contracts — do NOT collapse them into one parent.

### Consolidation patterns

When adding a feature, follow these patterns instead of growing the top-level
bin/ surface:

1. **Audit-aggregation** (`kaizen-gatekeeper`): a new code-quality check joins
   `SUB_GATES` in `skills/workflow/scripts/gatekeeper.py` — adds one row to
   the unified green/yellow/red verdict. Use this for any check whose output
   is "N findings of X kind". Examples: token-bloat, coverage, schema-coverage.
2. **Consolidated CLI parent** (`kaizen-brain`, `kaizen-statusline`):
   multi-verb dispatcher over a shared file family
   (`brain_index.py` + `brain_promote.py` + `brain_audit.py`; or
   `statusline_dxm.py` + `statusline_intent.py`). The parent script reads
   `$1` as the verb and `exec`s the matching backing module. Sibling bins
   for each verb stay (back-compat), declared `# consolidated-cli-parent: <parent>`
   in their docstring (iron-laws bin-naming exemption).
3. **MCP server without bin**: an MCP-only feature (loaded by Claude via
   `plugin.json::mcpServers`, not invoked through shell) does NOT need a
   `kaizen-<feature>-mcp` bin wrapper. The bin only exists when humans/scripts
   invoke the MCP script directly. Audit: MCPs in `*_mcp.py` that are only
   reached via Claude's MCP loader don't earn a bin slot.
4. **Schema-driven feature** (the 4 canonical shapes): every config-driven
   feature ships one of `lens-manifest` / `decision-rubric` / `plain-config` /
   `rule-catalog` under `skills/<feature>/domain/` PLUS matching
   `domain/schemas/*.schema.json`. Audit via `kaizen-schema-coverage`.

### Coverage family — naming axes (don't conflate them)

`coverage` is a category, not a single metric. The plugin distinguishes
**at least four axes** — each measures conformance against a different
target. Future audit additions should pick a fresh, specific name (avoid
the bare `coverage` token).

| Axis | Asks | Tool | Gate key | Status |
|---|---|---|---|---|
| **code-to-test-coverage** | does every `workflow/scripts/*.py` have a matching `tests/test_*.py`? (file-mapping presence — not runtime line coverage) | `kaizen-coverage` (bin) | `code-to-test-coverage` | shipped |
| **schema-coverage** | does every `domain/`-having feature match one of the 4 canonical shapes (lens-manifest / decision-rubric / plain-config / rule-catalog)? | `kaizen-schema-coverage` | `schema-coverage` | shipped |
| **name-quality-coverage** | does each filename match the file's stated intent (first docstring or header comment)? Catches `_subproc.py` whose docstring says "subprocess", junk-drawer names like `utils.py`, etc. | `kaizen-name-quality` | `name-quality-coverage` | shipped |
| **rubric-coverage** | does every feature that *should* use a decision rubric actually ship one? (subset of schema-coverage; flags cases where `--bundles` or routing logic would benefit from a rubric but uses ad-hoc Python) | future — partially answered by `kaizen-schema-coverage feature <name>` | (planned) | not built |
| **trace-coverage** | does every hook fire `_trace.sh` and every MCP server emit `kaizen-trace` events? | iron-laws law `every_hook_script_traces_its_firing` (partial) | `iron-laws` | partial — covers hooks, not MCPs |

When adding a new coverage axis, name it `<thing>-coverage` (hyphenated;
prefer specific phrasing — `code-to-test-coverage` beats `code-coverage`
because the latter implies *runtime line coverage* which we don't
measure here). Keep the bin as `kaizen-<thing>-coverage` for consistency
with the existing pair, and register it as its own SUB_GATES key in
gatekeeper (don't overload an existing axis).

### JSONL-indexed deliverables — fine-grained picking convention

For any output > ~30 structured entries (brainstorms, findings, audit
results, plan items, event slices), produce a paired `.jsonl` index
**alongside** the prose `.md`. Consumers query the JSONL with `jq` /
DuckDB / `python -c` to pick the exact slice they need — no need to
Read the prose file just to navigate to one entry.

**File layout convention:**
```
plans/<date>-<slug>.md         ← prose synthesis + cross-thread narrative
plans/<date>-<slug>.jsonl      ← indexed entries, one per line
```

**Entry shape (typical fields):**
```json
{"id": <int>, "round": <int>, "bucket": "<group>", "theme": "<sub>",
 "idea": "<one-line>", "tier": 1-4|null, "tools": ["..."],
 "status": "shipped|top-pick|deferred|research|long-arc|radical"}
```

**Query examples (all zero-Read):**
```bash
# All top-picks across all rounds
jq -r 'select(.status=="top-pick") | "#\(.id) [\(.bucket)] \(.idea)"' plans/*.jsonl

# Just round 5's SQL-bucket
jq -r 'select(.round==5 and .bucket|startswith("sql"))' plans/*.jsonl

# DuckDB: per-bucket counts (after R5#201 lands)
kaizen-sql 'SELECT bucket, COUNT(*) FROM "plans/*.jsonl" GROUP BY bucket'

# Python one-liner for ad-hoc joins
python3 -c "import json; [print(r['idea']) for r in
  (json.loads(l) for l in open('plans/<file>.jsonl')) if r.get('tier')==1]"
```

**Why:** the agent (or human) gets ~10 lines of relevant output instead
of reading 580 lines of prose to find them. Compounds heavily over a
long session — sister pattern to `kaizen-token-bloat read <citation>`
(jump straight to the cited lines, no whole-file Read) and
`kaizen-dxm append-to` (zero-roundtrip stream → file dump).

**When NOT to use:** single-purpose docs (CONTRIBUTING.md, ATTRIBUTIONS.md,
this CLAUDE.md), narrative-only outputs (handoff prose), and anything
< 30 structured entries (the indexing overhead doesn't pay back).

### Audit surface (one-command sanity)

```bash
kaizen-gatekeeper check --all   # 8 sub-gates aggregated (one verdict)
kaizen-token-bloat scan         # bloat axis: per-tier waste across loaded content
kaizen-coverage gaps            # code-to-test-coverage axis: 1:1 script ↔ test-file presence
kaizen-schema-coverage gaps     # schema-coverage axis: feature shape conformance
kaizen-name-quality gaps        # name-quality axis: filename ↔ docstring intent match
```

All four also fire automatically — the SessionEnd hook refreshes the
token-bloat cache, `kaizen-gatekeeper` runs in the pre-commit gate's
unified verdict, and `kaizen-schema-coverage` surfaces via gatekeeper now too.
