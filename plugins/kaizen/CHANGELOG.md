# Changelog

All notable changes to the `kaizen` plugin documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [1.13.0] — 2026-05-12

Research → implement based on two external sources:

- [Presta vibe-coding checklist](https://wearepresta.com/vibe-coding-tips-checklist-avoid-breaking-builds/) — AI-as-draft discipline, pre-commit + review checklists, governance/traceability.
- [intent-driven.dev OpenSpec custom schemas](https://intent-driven.dev/blog/2026/02/12/openspec-custom-schemas/) — declarative yaml workflow schemas with markdown templates.

### Added — `kaizen:vibe-check` skill + slash command + diff-aware script

**Skill**: `skills/vibe-check/SKILL.md` — full AI-coding discipline encoded as a kaizen skill. Codifies the Presta checklist with kaizen's gate-integration recipe: pre-commit checklist, anti-patterns, safe prompt patterns, review checklist, governance via commit-message markers + trace audit, gradual adoption phases, Iron Laws.

**Slash command**: `/kaizen:vibe-check` runs `scripts/vibe_check.sh` against the staged diff. Augments `/kaizen:gate` with 5 AI-specific checks:

1. Gate dry-run (delegates to `pre-commit.sh`)
2. New exported fns vs new tests imbalance (Rust + JS/TS heuristics)
3. Orphan imports — new `use` statements referencing crates not yet in any `Cargo.toml`
4. Commit-message marker check — `[AI]` / `AI-assisted` / `AI:generated` presence
5. Diff size advisory — flag >15-file diffs per kaizen sizing rule

Advisory only — never blocks (the existing `/kaizen:gate` is the enforcement layer; vibe-check augments).

### Added — `schemas/` scaffold (declarative workflow schemas)

OpenSpec-inspired yaml schemas with markdown templates, shipped as a scaffold for the v1.14.0+ workflow-runtime migration:

- `schemas/minimalist/{schema.yaml,templates/specs/spec.md,templates/tasks/tasks.md}` — 2-artifact low-ceremony workflow (specs as Given/When/Then → tasks).
- `schemas/kaizen-default/schema.yaml` — 8-artifact full kaizen routine (research → explore → analyze → plan → tasks → execute → review → validate) as declarative yaml. Mirrors the existing hardcoded `workflow-routing` routines without breaking them.

Resolution order (when v1.14.0+ wires the loader): project (`.workflow/schemas/`) → user (`~/.claude/kaizen-schemas/`) → built-in (this dir).

### Added — `docs/workflow-schemas-research.md`

Design doc for the v1.14.0+ migration. Covers: why declarative beats hardcoded, the schema format, agent consumption pattern, strangler-fig migration plan (v1.13.0 → v2.0.0 over 5 minor + 1 major release), open questions to resolve with empirical use.

### Deferred

- Workflow runtime that loads + executes schemas (v1.14.0+).
- Brain-rule type `dependency-allowlist` integration with vibe-check's orphan-import check (would let users define `allowlist: [serde, tokio, ...]`). Pattern already established in v1.2.0's brain-rule system; wiring is a v1.13.x follow-up.

### Why minor (1.12.0 → 1.13.0)

New skill + new slash command + new script + scaffold for a future declarative system. Additive surface; no breaking changes.

## [1.12.0] — 2026-05-12

Three hardening tracks land together.

### Changed — trace-search defaults to **CPU torch** (GPU opt-in)

v1.11.0 shipped sentence-transformers with `torch` from default PyPI, which pulled ~3.5 GB of CUDA runtime libraries even on CPU-only flows. v1.12.0 inverts the default:

- **CPU default** (`trace_index.py`): PEP 723 inline-metadata pins `torch` to `https://download.pytorch.org/whl/cpu` — ~200 MB venv (vs ~3.5 GB GPU). Fast enough for inference of `all-MiniLM-L6-v2`.
- **GPU opt-in** (`trace_index_gpu.py`, NEW): thin `runpy.run_path` shim with default-PyPI torch. Auto-installs CUDA wheels on Linux.
- **Wrapper switch** (`bin/kaizen-trace-index`): `KAIZEN_TRACE_GPU=1 kaizen-trace-index ...` picks the GPU script; default picks CPU.
- **MCP server** (`trace_mcp.py`): always CPU — long-running server rarely benefits from GPU for short embedding calls. Document escape hatch via CLI for batch reindex.

The GPU venv from v1.11.0 stays cached and usable when toggled via env var. The new CPU venv is a separate uv-managed slot (~200 MB). Switch modes freely — both share the same SQLite store; embeddings are model+dim-tagged in `trace_meta` so they're forward-compatible.

### Added — installer hardening (preflight checks + install log)

`install.sh` now logs every install to `~/.claude/kaizen-install.log` with ISO timestamps. Before touching the repo, it runs preflight checks:

- **Required**: `git`, `python3` — abort with clear message if missing.
- **Advisories** (non-fatal, surface only): `uv` not on PATH (trace-index + MCP servers won't auto-install deps); `$HOME/.local/bin` not on PATH (kaizen-* symlinks unfindable from shell).

Each advisory points at the fix (e.g. `curl -LsSf https://astral.sh/uv/install.sh | sh`, `export PATH=$HOME/.local/bin:$PATH`). Install continues either way — no silent failures.

### Added — `config.py --validate` for `.kaizen.toml` schema checks

New subcommand `kaizen-config --validate` (and `python3 config.py --validate`) checks the loaded config against `KNOWN_KEYS` and filesystem reality:

- **Schema warnings**: unknown top-level keys (typo or future-version field) — surface, don't block.
- **Filesystem warnings**: `backlog_path` parent dir absent; `compile_check_cmd` first word not on PATH; `brain_path` doesn't exist.
- Exit 0 if only warnings; exit 1 only on hard errors (none defined yet — placeholder for future ones).

`KNOWN_KEYS` includes the 4 default keys plus 7 commonly-observed extensions (`plan_dir`, `allow_deletion_env`, `skip_tdd_check_env`, `brain_path`, `project_memory_path`, `trace_embedding_model`, `trace_index_path`).

### Bumps minor (1.11.0 → 1.12.0)

CPU default is a behavior change for `kaizen-trace-index` — but the GPU path remains accessible via env var, so it's additive in capability. Installer hardening is observable surface. Config validate is purely new.

### Why minor not patch

CPU default fundamentally changes which venv `uv run` resolves on a fresh install — disk footprint drops from ~3.5 GB to ~200 MB. Worth marking as a meaningful release.

## [1.11.0] — 2026-05-12

### Added — SQLite-backed semantic search over kaizen trace (sentence-transformers)

`scripts/trace_index.py` + `scripts/trace_mcp.py` + `bin/kaizen-trace-index` + `commands/trace-search.md` + new MCP server registration.

L3 trace events are now indexed into SQLite at `~/.claude/.kaizen-trace/index.db` with 384-dim embeddings from `sentence-transformers` (default model: `all-MiniLM-L6-v2`). Cosine similarity ranks search hits. SQL pre-filters by `src` / `sid` / `evt` / `since` before scoring for speed at scale.

PEP 723 inline-script-metadata declares `sentence-transformers + numpy` as deps. uv reads it on first invocation and resolves a cached venv (~500MB w/ torch; ~80MB model weights from HuggingFace). Cold start ~30s once; warm searches sub-second.

**Privacy model**: by default ONLY the event signature is embedded (`src + evt + tool + sid_prefix + latency_category`). NO commands, file paths, prompts, or payload data participate in the vector. `--embed-data` opt-in adds safe fields (`model`, `status`, `verdict`, `outcome`, `kind`). Sensitive fields are NEVER embedded regardless of flag.

**SQLite schema**:

- `trace_events(id, ts, src, evt, sid, tool, ms, data_json, embedding BLOB, content_hash UNIQUE)` — indexed on ts/src/sid/evt.
- `trace_meta(key, value)` — model name, dim, last_indexed_ts, total_events.

Content-hash dedup keys on `ts|src|evt|sid|tool|ms` — incremental indexing skips already-stored events on re-runs.

### Subcommands (`kaizen-trace-index`)

- `index [--max N] [--embed-data]` — incremental
- `reindex [--embed-data]` — wipe + rebuild
- `search "<query>" [--top-k 10] [--src S --sid SID --evt E --since 1h] [--json]`
- `stats` — total indexed, model, dim, ts range
- `get <id>` — fetch event by SQLite id (returned by search)
- `path` / `clear`

### MCP server `kaizen-trace-search`

Registered in `.mcp.json` as the second on-demand MCP server (after `kaizen-browser`). Five tools exposed to Claude (`mcp__plugin_kaizen_kaizen-trace-search__*`):

- `trace_search(query, top_k, src, sid, evt, since)` — semantic search
- `trace_index_status()` — health (total events, model, ts range)
- `trace_index_run(embed_data, max_n)` — incremental re-index
- `trace_get(event_id)` — fetch by id
- `trace_recent(limit, src)` — latest N by ts (no ranking — fast)

The MCP server keeps a sentence-transformers model loaded across tool calls (~500MB RAM after first call; instant embeddings thereafter).

### Composition

- L3 trace events (events.jsonl) → indexed here as a queryable layer
- v1.9.0 `schemas.TraceEvent` validates on read upstream; trace-index assumes valid events
- v1.10.0 `kaizen-observe drill` is the broad cross-layer report; trace-search is the deep semantic-narrow query
- v1.7.x browser MCP events flow through hooks → already in trace → searchable here

### Why sentence-transformers (not TF-IDF or fastembed)

User explicitly requested `from sentence_transformers import SentenceTransformer` (sbert.net). Heavier (~500MB w/ torch dep) but gold-standard quality, well-supported, broad model catalog. Future micros can offer a lighter `fastembed` adapter behind the same SQL+MCP surface if size becomes a concern.

### Bumps minor (1.10.0 → 1.11.0)

Two new scripts + one new MCP server + one bin wrapper + one slash command. Additive; no breaking changes. Deferred: daemon integration to auto-index on each tick (manual `index` needed for now).

## [1.10.0] — 2026-05-12

### Added — `kaizen-observe` (unified 6-layer observability)

`scripts/observe.py` + `bin/kaizen-observe` + `/kaizen:observe`. Implements the synthesis described in the user's prior 6-layer enumeration: a single tool that reads across CC transcript / kaizen trace / domain logs / per-repo state / plugin state, with schema-driven validation (uses v1.9.0 `schemas.py`) and the canonical drill-down recipe automated.

The 6 layers covered:

- **L1** live UI / stderr (ephemeral, skipped)
- **L2** CC transcript JSONL at `~/.claude/projects/<slug>/<sid>.jsonl`
- **L3** kaizen trace at `~/.claude/.kaizen-trace/events.jsonl` (+ rotated `.gz`)
- **L4** domain logs: daemon log, llm-proxy log, inbox JSONs, /tmp/kaizen-compile.log
- **L5** per-repo state: `.workflow/`, `.kaizen/cache/`, `.kaizen.toml`
- **L6** plugin + global: `installed_plugins.json`, `settings.json`, backups, brain Notes

**Subcommands**:

- `layers` — JSON summary of all 6 (default if no arg). Shows sizes, counts, last activity per layer.
- `query --sid SID --src S --evt E --since 1h [--json]` — unified L3-indexed query.
- `stats --since 1h [--sid SID]` — counts + p50/p95/max latency. Flags schema-invalid records.
- `drill <sid>` — automated drill-down recipe → Markdown report walking all 6 layers, with recommended next-step list at the end.
- `snapshot [--name NAME]` — content-hashed capture of all layer summaries. Stored at `~/.claude/.kaizen-observe/snapshots/`. Deterministic: byte-identical state produces byte-identical snapshot bytes.
- `compare <a> <b>` — diff two snapshots; reports which layers changed.
- `snapshots` — list saved snapshots.

**Schema-driven**: L3 trace events validated via `schemas.TraceEvent` from v1.9.0. Invalid records (bad `src` enum, missing `evt`, negative `ms`) are flagged with `_validation_errors` field and counted in `stats.invalid`. Other layers fall through as raw JSON; the dataclass scaffold is in place for future adoption (`InboxMessage`, `DaemonState`).

**Dynamic vs deterministic**: `query`/`stats`/`tail` are real-time reads (dynamic). `snapshot`/`compare` are content-hashed captures (deterministic). Use deterministic mode for reproducible point-in-time analysis ("was this layer state different before X happened?") and regression detection.

**Drill-down recipe** (automated):

1. L3 trace stats (the fast index)
2. L3 event sample for the sid
3. L2 transcript path + size hint
4. L4 domain logs if errors / pending inbox / proxy events detected
5. L5 per-repo state from cwd
6. L6 plugin/global counts

The report ends with a "Recommended next steps" list pointing at the next tool to invoke given what was found.

### Composition with prior versions

- v1.6.x trace events → v1.10.0 L3 reader
- v1.9.0 schemas dataclasses → v1.10.0 validation layer
- v1.4.x inbox → v1.10.0 L4 reader
- v1.5.x daemon → v1.10.0 L4 reader
- v1.7.x browser MCP events flow through hooks → already in L3
- v1.8.0 `kaizen:agent-brief` listed the 6 layers; v1.10.0 makes them queryable

No new instrumentation — `observe` is a pure reader. Adopt-as-needed.

### Bumps minor (1.9.0 → 1.10.0)

New script + bin wrapper + slash command. Additive surface. No breaking changes.

### Bugfix

`l5_summary` previously crashed on completed workflow state (`current` index beyond `stages` length). Bounds-checked: reports `"(complete or out-of-range)"` instead.

## [1.9.0] — 2026-05-12

Three changes from the SDD/SSOT research doc landing together: an inbox drain timing fix (the "already-addressed echo" bug surfaced by the user), OPP-A (`.kaizen.toml` SSOT via `config.py`), and OPP-B (dataclass schemas in `scripts/schemas.py`).

### Fixed — inbox drain replays the turn-starting prompt back to Claude

The v1.4.0 inbox + drain hooks captured the user's current prompt via UserPromptSubmit, then on the very next PostToolUse the drain surfaced it as a "while you were busy" message. Claude saw what looked like a new message and replied "Already addressed — that's the X I just did," producing a visible feedback loop the user found annoying and wrong.

**Root cause**: drain treated ALL pending messages identically. The turn-starter (the prompt that initiated the current assistant turn) is conceptually different from mid-turn interrupts — only the latter should surface as "while you were busy".

**Fix**: sentinel file `~/.claude/kaizen-inbox/.current-turn` holds the turn-starter's filename + timestamp.

- `UserPromptSubmit` hook calls `inbox.py set-turn-starter <path>` — writes sentinel ONLY IF absent (mid-turn prompts don't overwrite).
- `inbox.py drain` reads the sentinel and skips the file it references. All other pending messages surface normally.
- `Stop` hook calls `inbox.py clear-turn-starter` — removes the sentinel AND marks the starter as `drained: true` with `drain_reason: "turn-starter-completed"`. Next turn's starter then becomes the new sentinel.

Smoke-tested across a 4-step turn lifecycle (P1 starter → mid-turn P2 → P3 next-turn-starter). Mid-turn interrupts still surface; turn-starters never do.

### Added — `scripts/config.py` as `.kaizen.toml` SSOT (OPP-A)

Stdlib-only TOML parser shared by all kaizen scripts. Three call sites (`statusline.sh`, `install.sh`, eventually `pre-commit.sh`) previously re-implemented `grep -E '^key' | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/'` — a typo would silently corrupt one consumer while leaving others working.

**API**:

```python
from config import load_config, get
cfg = load_config()                  # auto-finds repo root
val = get("backlog_path", default=".workflow/backlog.md")
```

**CLI for bash**:

```bash
python3 config.py                          # all key=value
python3 config.py backlog_path             # one key
python3 config.py X --default "fallback"   # with default
python3 config.py --json                   # full as JSON
python3 config.py --path                   # location of .kaizen.toml
```

**Consumers migrated**: `statusline.sh` and `install.sh` replaced their 4-line `grep+sed` blocks with a single `python3 config.py backlog_path --default ...` call.

**Deferred**: `pre-commit.sh` keeps its internal `toml_get()` helper for now — it's already factored within the script and lifts ~7 keys. A future micro will delegate it to `config.py` for full unification.

### Added — `scripts/schemas.py` with dataclass SSOTs (OPP-B)

Four kaizen JSON shapes had lived only in comments + scattered field accesses. Now declared once:

- `TraceEvent` — `~/.claude/.kaizen-trace/events.jsonl` records (with `validate()` checking valid `src` enum + `ms >= 0`).
- `InboxMessage` — `~/.claude/kaizen-inbox/<ts>-<n>.json` files (added `drain_reason` field).
- `DaemonState` — `~/.claude/.kaizen-daemon/state.json`.
- `BacklogItem`, `BacklogDecision`, `BacklogStore` — `<repo>/.workflow/backlog.json` envelope (available for future `backlog.py` migration; not yet adopted by the writer).

**Compat policy**:

- `from_dict()` IGNORES unknown fields (forward-compat: newer writers can add fields older readers don't know).
- Missing fields fall back to dataclass defaults (backward-compat: older writers' files load under newer readers).
- Adopt one writer at a time; on-disk shape stays compatible throughout.

**Tests**: `tests/test_schemas.py` — 15 tests covering round-trips, validation errors, forward/backward-compat. All green.

**Self-test**: `python3 schemas.py` runs an executable contract — exits 0 with "all schema round-trips pass" if the module is internally consistent.

### Not yet adopted by writers

This release ships the schema DECLARATIONS. Writers (`trace.py`, `inbox.py`, `daemon.py`, `backlog.py`) still construct dicts directly. A follow-up micro will migrate each writer one at a time — each migration is a behavior-preserving refactor (caller view + on-disk shape unchanged) but lets a future change harden a single field's type / validation in one place.

### Bumps minor (1.8.0 → 1.9.0)

Two new modules + one bug fix. No breaking changes — every existing call site still works without using the new APIs.

## [1.8.0] — 2026-05-12

### Added — `kaizen:agent-brief` (machine-readable capability map)

New skill at `skills/agent-brief/SKILL.md`. Dense, AI-facing orientation document for fresh agents / subagents entering a kaizen-installed repo or session. Replaces the human-oriented `/kaizen:menu` flow for LLM consumers.

**What's in it** (no prose — operational, table-driven):

| Section | Content |
|---|---|
| Detection | bash one-liners to check if kaizen is active in current repo + session |
| 8 capability layers | gate (12 checks), backlog, agents (3), trace, LLM proxy, daemon/watcher, browser MCP, bin wrappers — each with exact paths + invocations |
| Failure modes | 6 symptoms × cause × recovery — `Unknown command`, cache stale, gate fail, pre-deletion block, inbox pending, browser sync-API error |
| Common tasks | 11 frequent agent tasks → exact CLI / slash / MCP invocation |
| State data streams | 13 file locations (CC transcript, trace, inbox, daemon, proxy, cache, compile log, backlog, workflow state, architecture log, snapshot, backups, brain rules) |
| Deeper skill pointers | 9 trigger → `kaizen:<sub>` skill mappings (`onion-ddd-workflow`, `tdd`, principle skills, `behaviour-config`, `publishing`, `writing-skills`, `writing-plans`, `plugin-pitfalls`) |
| Iron Laws | 6 non-negotiable rules every agent action must respect |

### Triggers

The skill's `description:` lists ~12 phrases that fire it, including:

- "tell me about kaizen" / "what does kaizen do"
- "orient me in this repo" / "kaizen overview"
- "fresh session in kaizen repo" / "subagent kaizen handoff"
- "kaizen capabilities" / "what's installed here"

The agent reads the body end-to-end (per the global skill-reading rule) BEFORE touching any `/kaizen:*` command, ensuring it understands the surface area + Iron Laws without re-deriving from individual command help.

### Why

Every prior session that entered a kaizen-installed repo had to either (a) probe with `/kaizen:menu`, `/kaizen:status`, etc. — token-expensive — or (b) operate blind and trip the gate. `agent-brief` collapses that orientation to a single skill load.

Bumps minor (1.7.1 → 1.8.0). No code surface changes; pure new skill.

## [1.7.1] — 2026-05-12

### Fixed — browser_mcp.py: switched sync_playwright → async_playwright

v1.7.0 used `playwright.sync_api.sync_playwright` inside FastMCP's tools. FastMCP runs in an asyncio event loop, and Playwright explicitly rejects its sync API in that context:

```
Error executing tool open_browser: It looks like you are using Playwright
Sync API inside the asyncio loop. Please use the Async API instead.
```

Discovered on first real `open_browser(headless=True)` invocation. Symptom: every tool fails immediately with the above error.

**Fix**: rewrote `browser_mcp.py` to use `playwright.async_api.async_playwright`. All 14 `@mcp.tool()` functions are now `async def`, and every Playwright call is awaited. Tool signatures, return values, and module-global state shape unchanged — fully backward-compatible from the caller's view.

Lifecycle detail: `_pw_cm = async_playwright()` is the async context manager; we `__aenter__` it on `open_browser` and `__aexit__` on `close_browser`. Stored at module scope so calls span tool boundaries within one MCP server lifetime.

## [1.7.0] — 2026-05-12

### Added — Playwright-backed browser MCP server

Claude now has a real browser to drive. `scripts/browser_mcp.py` is a FastMCP server wrapping Playwright (sync_api). Registered in `.mcp.json` as `kaizen-browser`; spawned on-demand by Claude Code when the first `mcp__kaizen-browser__*` tool is invoked.

**14 tools** — primitives, not AI-planned actions (Claude does the planning natively):

| Tool | Purpose |
|---|---|
| `open_browser(headless, viewport_*)` | launch Chromium + create page |
| `close_browser` | tear down |
| `navigate(url, wait_until)` | go to URL |
| `current_url` | where am I |
| `click(selector, timeout_ms)` | CSS / `text=…` / `role=…` / any Playwright locator |
| `type_text(selector, text, timeout_ms)` | fill input/textarea (clears first) |
| `press_key(key)` | Enter / Tab / Escape / Arrow… |
| `wait_for(selector, state, timeout_ms)` | attached / visible / detached / hidden |
| `get_text(selector="body")` | inner_text |
| `get_html(selector="html")` | outerHTML |
| `screenshot(path, full_page)` | PNG → CC Read tool renders inline |
| `list_links` | all `<a href>` (text + URL, cap 50) |
| `list_inputs` | all form fields (name+type+value, cap 30) |
| `evaluate(js_expression)` | run arbitrary JS in page (power-tool) |

**bin/kaizen-browser** — install / check / status / path / fg subcommands. Auto-symlinked into `~/.local/bin/` by `/kaizen:install` (v1.4.2 zero-config).

**commands/browser.md** — `/kaizen:browser` slash command wrapping the wrapper.

### Why these primitives, not AI-planned actions

`browser-use`, `Stagehand`, and similar add a second LLM that plans selectors and intents. Powerful but adds latency, cost, and a model to maintain. `kaizen-browser` exposes primitives only — Claude does the planning natively from CSS/DOM knowledge. Fewer moving parts, full visibility through CC's tool boundary, fits the kaizen "minimum-correct + maximum-trace" style.

### Composition

- **Trace**: every browser tool call fires `PreToolUse-*` / `PostToolUse-*` hooks → `kaizen-trace --src hook tool=mcp__kaizen-browser__*` for replay + latency.
- **LLM proxy**: with `ANTHROPIC_BASE_URL=http://127.0.0.1:8765`, Claude's *selector planning* also traces as `src=llm`. End-to-end browser-workflow observability.
- **Inbox**: messages typed during a multi-step browser workflow surface on the next tool boundary.

### Install

`pip install --user mcp playwright` + `python -m playwright install chromium` (~150 MB one-time). Or run:

```
/kaizen:browser install
/reload-plugins
/kaizen:browser status
```

Then in any CC conversation:

```
"Open browser to news.ycombinator.com, list the top 10 story titles"
→ Claude calls: open_browser, navigate, get_text or list_links, returns
```

State persists across tool calls within a CC session (cookies, scroll, page). Server dies at CC exit; `close_browser` is optional.

### Soft dependency

The MCP server's import fails fast with a clear stderr message + exit 1 if `mcp` or `playwright` aren't installed. The wrapper's `check` subcommand verifies both Python modules AND that Chromium can launch — catches the common "pip-installed but `playwright install chromium` skipped" gotcha.

## [1.6.3] — 2026-05-12

### Added — full 8+1 coding-skills suggestion engine in pre-commit gate

The pre-commit gate previously emitted skill suggestions for only 2 principles (KISS+SoC on large diffs, onion-ddd-workflow on dep changes). Expanded to all 8 coding-skills + TDD via fast diff heuristics. Suggestions are advisory; never block.

**Trigger table** (each heuristic runs on `git diff --cached`, ~10 ms on small diffs):

| # | Skill | Trigger |
|---|---|---|
| 1 | `onion-ddd-workflow` | `Cargo.toml` / `package.json` / `go.mod` dep added or removed |
| 2 | `coding-skills:kiss` + `coding-skills:separation-of-concerns` | Single file with >100 staged lines (excl. tests) |
| 3 | `coding-skills:dry` | Same string literal (>40 chars) appears 2+ times in additions |
| 4 | `coding-skills:solid` | Single file adds 8+ `pub fn` (interface-segregation + SRP hint) |
| 5 | `coding-skills:law-of-demeter` | 2+ lines with 4-level method chains `.a().b().c().d(` in additions |
| 6 | `coding-skills:yagni` | New `#[cfg(feature = "...")]` gate OR `pub trait` with no `impl X for` in same diff |
| 7 | `coding-skills:boy-scout-rule` | TODO/FIXME/HACK/XXX within ±10 lines of staged changes |
| 8 | `coding-skills:convention-over-configuration` | New file extension diverges from sibling files in same dir |
| 9 | `tdd` | Net-new non-test source file added (positive nudge; Check #7 still warns on missing paired tests) |

Plus a **meta-trigger**: if 3+ suggestions fire AND the diff is structural, surface `onion-ddd-workflow` umbrella for the umbrella review.

### Bugfix — `grep -c ... || echo 0` produced "0\n0"

`grep -c` exits 1 when no matches but still prints `0` to stdout. The fallback `|| echo 0` appended a second `0`, making the variable multi-line. `[ "0\n0" -ge 1 ]` then errored with `integer expression expected`. Fix: drop the redundant `|| echo 0`; trust grep's output. Apply `2>/dev/null` to the `[` test as belt-and-suspenders.

### Smoke

Synthetic file triggering 5 principles in one diff:

```
✓ Large single-file diff → skill: coding-skills:kiss + coding-skills:separation-of-concerns
✓ Repeated string literals in staged adds → skill: coding-skills:dry
✓ File adds 8+ pub fn → skill: coding-skills:solid (interface segregation, single-responsibility)
✓ New feature-flag(s) or zero-impl trait → skill: coding-skills:yagni
✓ Net-new source file(s) added → skill: tdd (or coding-skills equivalent)
```

Zero false positives, zero bash errors. Real-world repos exercise the trigger surface in normal commits — gate stays sub-100ms on typical diffs.

## [1.6.2] — 2026-05-12

### Quality pass — DRY + KISS + hardening

**DRY** — extracted `hooks/_trace.sh`. The 3-line trace pattern (extract `session_id`, call `trace.py event --src hook`) lived in all 7 hooks pre-v1.6.2. Now centralized:

```bash
# Old: 3 lines × 7 hooks = 21 lines of duplicated boilerplate
KZ_SID=$(printf '%s' "$EVENT" | python3 -c "..." 2>/dev/null)
python3 "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/trace.py" event \
    --src hook --evt X [--tool Y] ${KZ_SID:+--sid "$KZ_SID"} >/dev/null 2>&1 || true

# New: 1 line × 7 hooks = 7 lines total
printf '%s' "$EVENT" | bash "${CLAUDE_PLUGIN_ROOT}/hooks/_trace.sh" X [Y]
```

`_trace.sh` reads stdin once, extracts session_id, emits the trace event. Trace-call logic lives in ONE place; future changes touch one file, not seven. Eliminates a future "fix 7 hooks identically" foot-gun.

Verified end-to-end: all 7 hooks still emit correctly tagged events with sid + tool; no payload leakage.

**Hardening** — `llm_proxy.py` request body size cap:

```python
MAX_BODY_BYTES = 50 * 1024 * 1024   # 50 MB

if content_len > MAX_BODY_BYTES:
    trace_event("body-too-large", content_length=content_len, limit=MAX_BODY_BYTES)
    self.send_error(413, ...)
    return
```

Defends against DoS via crafted `Content-Length` headers. 50 MB is generous (max Anthropic message size + attachments) but bounds memory use. Trace records the violation under `src=llm evt=body-too-large` for debugging.

**KISS** — no other simplification candidates in this pass. `trace.py` SSE parsing (walk backwards for `message_delta`) is the simplest workable approach for streaming token extraction. `llm_proxy.py` Connection: close keeps response handling trivial (no chunked re-encoding).

### Audit findings (no fix needed)

- `trace.py --since` regex handles `1h/30m/7d/Ns` cleanly; ISO fallback covers edge cases.
- `trace.py` p95 latency falls back to `max` for samples < 20 — acceptable for small windows.
- `llm_proxy.py` path concatenation (`upstream_base + self.path`) can't escape the upstream base (string concat, not `urljoin`), so path-traversal attacks are inert.
- `llm_proxy.py` always passes auth headers to upstream but never includes them in trace events — verified via curl smoke test with `Bearer SECRET-…` payload.

## [1.6.1] — 2026-05-12

### Added — Anthropic API logging proxy

**`scripts/llm_proxy.py`** — stdlib-only HTTP forwarding proxy that wraps the Claude Code ↔ `api.anthropic.com` connection. Each request/response logs to `kaizen-trace --src llm` with:

- Request: `path`, `model`, `messages` count, `system_chars`, `max_tokens`, `stream`
- Response: `status`, `input_tokens`, `output_tokens`, `ms`

**Auth scrubbed** — `Authorization`, `x-api-key`, `anthropic-auth`, `Cookie`, `Set-Cookie` headers pass through to upstream but are NEVER written to trace data.

**Streaming SSE** handled correctly — chunks pass through to client untouched (`Connection: close` semantics, no chunked re-encoding hassles). Final `message_delta` event captured for `output_tokens`.

**`bin/kaizen-trace-proxy`** — manage the proxy:

| arg | effect |
|---|---|
| `start [--port N] [--upstream URL]` | spawn detached (default `127.0.0.1:8765` → `api.anthropic.com`) |
| `stop` | SIGTERM → 3 s → SIGKILL |
| `status` | running yes/no + export hint |
| `log [N]` | tail proxy stdout |
| `fg [--port --upstream]` | foreground (systemd `ExecStart`) |

PID file: `~/.claude/.kaizen-daemon/llm-proxy.pid`. Log: `…/llm-proxy.log`.

**Usage**:

```bash
kaizen-trace-proxy start
export ANTHROPIC_BASE_URL=http://127.0.0.1:8765
# All subsequent CC sessions in this shell trace LLM calls
```

### Fixed — hook tracing was leaking tool_input verbatim (SECURITY)

v1.6.0 hooks piped the entire event JSON into `trace.py event --data`, which captured `tool_input` and `tool_response` (containing command lines, edit diffs, file contents). A `curl -H "Authorization: Bearer …"` ran via Bash tool would land the secret in the trace log.

**Fix**: all 7 kaizen hooks now extract ONLY `session_id` from the event and pass it as `--sid`. No `--data`, no stdin pipe. Trace records the essential metadata (event name, tool name, sid, timestamp) without any user payload.

Pattern (before):

```bash
printf '%s' "$EVENT" | trace.py event --src hook --evt PreToolUse-bash --tool Bash
# → trace data field contained full tool_input.command
```

Pattern (after):

```bash
KZ_SID=$(printf '%s' "$EVENT" | python3 -c "import json,sys; print(json.loads(sys.stdin.read() or '{}').get('session_id',''))")
trace.py event --src hook --evt PreToolUse-bash --tool Bash ${KZ_SID:+--sid "$KZ_SID"}
# → trace records only event + tool + sid
```

**If you ran v1.6.0 with active sessions**, your `~/.claude/.kaizen-trace/events.jsonl` may contain captured tool_input data including any secrets typed into Bash/Edit/Write. Recommended:

```bash
kaizen-trace clear        # wipe current + rotated trace files
```

before continuing.

Trade-off: less debugging info per event (no `tool_input.command`, `tool_response.stdout` in the trace). If you need that data, query the Claude Code transcript directly (`~/.claude/projects/<slug>/<sid>.jsonl`) — but that file is user-controlled.

## [1.6.0] — 2026-05-12

### Added — unified tracing (`scripts/trace.py` + hook integration)

Single append-only JSONL event log at `~/.claude/.kaizen-trace/events.jsonl` capturing structured events across hooks, agents, LLM calls, tool boundaries, and user actions. Fast queries, auto-rotation, retention pruning.

**Schema** (one JSON object per line):

```json
{
  "ts":   "2026-05-12T00:30:00.123Z",
  "src":  "hook|agent|llm|tool|user|cc|plugin",
  "evt":  "PreToolUse|invoke|complete|prompt|...",
  "sid":  "<session_id or empty>",
  "tool": "<tool name if applicable>",
  "ms":   <duration_ms or null>,
  "data": { ...arbitrary structured detail... }
}
```

**Subcommands**:

| arg | effect |
|---|---|
| (none) or `tail [-n N] [--src S] [--evt E]` | last N events |
| `query --since DURATION [--src --evt --tool --sid --json --count]` | filter (`1h`, `30m`, `7d`, or ISO ts) |
| `stats [--since DURATION]` | counts by src/evt/tool + p50/p95/max latency where `ms` set |
| `event --src S --evt E [--tool --sid --ms --data JSON]` | append manual event (stdin JSON merges into data) |
| `clear` / `path` | hygiene |

**Hook integration** — all 7 kaizen hooks now emit trace events:

| Hook | Event |
|---|---|
| `session-surface-backlog.sh` | `SessionStart` |
| `userprompt-inbox.sh` | `UserPromptSubmit` |
| `pretooluse-bash-gate.sh` | `PreToolUse-bash` (tool=Bash) |
| `posttooluse-bash-commit.sh` | `PostToolUse-bash` (tool=Bash) |
| `posttooluse-drain-inbox.sh` | `PostToolUse-drain` |
| `stop-backlog-reminder.sh` | `Stop` |
| `precompact-snapshot.sh` | `PreCompact` |

Pattern: `printf '%s' "$EVENT" | trace.py event --src hook --evt <name>`. stdin event JSON is merged into the `data` field of the trace record, preserving session_id, cwd, tool_name, tool_input/response for replay.

**Non-blocking** — trace failures swallow silently. `KAIZEN_TRACE_DISABLE=1` for production silence.

**Rotation + retention**:

| Knob | Default |
|---|---|
| `KAIZEN_TRACE_MAX_MB` | 100 — rotate to `events-YYYYMMDD-HHMMSSZ.jsonl.gz` |
| `KAIZEN_TRACE_RETENTION_DAYS` | 7 — auto-prune old rotated files |
| `KAIZEN_TRACE_DIR` | `~/.claude/.kaizen-trace` |

**`bin/kaizen-trace`** — auto-symlinked into `~/.local/bin/` by `/kaizen:install`. Available as `kaizen trace ...` (multiplexer) or `kaizen-trace` (direct).

### Sources instrumented vs. planned

- ✅ hook — all 7 kaizen hooks emit on entry
- ✅ user — via UserPromptSubmit hook
- ✅ plugin — daemon/watcher emit on tick + drift (already used in daemon.py log; can move to trace.py in a follow-up)
- ⚠ agent — agents can call trace.py from their invocation contract (documented; not auto-wired since agents are Claude-side dispatch)
- ⚠ llm — local-LLM call tracing requires a wrapper or OpenAI-compatible proxy (v1.6.x follow-up)
- ⚠ cc — covered indirectly via hooks (PreToolUse/PostToolUse already trace tool boundaries); no separate cc-internals source

### Example queries

```bash
kaizen-trace                                         # last 20 events
kaizen-trace query --since 1h --src hook             # all hook fires this hour
kaizen-trace query --src tool --tool Bash --since 30m
kaizen-trace stats --since 24h                       # latency p50/p95/max
kaizen-trace query --sid <uuid> --json | jq         # session replay
```

## [1.5.2] — 2026-05-11

### Added — keep-alive watcher mode (instant hash-drift detection)

Beyond the v1.5.0 cron mode (periodic ticks), the daemon now ships a **long-running watcher** that hash-polls the plugin source every N seconds (default 5) and reacts to **content drift** within seconds — instead of waiting up to 30 minutes for the next cron tick.

**Stdlib-only.** No `inotify` / `watchdog` dependency. The hash compare is fast (~10 ms for ~50 files), and a sleep-loop with `asyncio.wait_for(stop_event, timeout=interval)` lets SIGTERM cut in immediately without blocking on a poll cycle.

**Subcommands** (added to `scripts/daemon.py`):

| arg | effect |
|---|---|
| `watch [--interval SEC]` | foreground loop (use for systemd `ExecStart`, manual testing) |
| `watch-start [--interval SEC]` | spawn detached child via `start_new_session=True` (nohup-equivalent) |
| `watch-stop` | SIGTERM (waits 3 s) → SIGKILL fallback |
| `watch-status` | print state; exit 0 if running / 1 if not (scriptable) |

**`bin/kaizen-watch`** — convenience wrapper with `start | stop | status | fg` shorthand. Auto-symlinked into `~/.local/bin/` by `/kaizen:install`.

**PID file** at `~/.claude/.kaizen-daemon/watcher.pid`. Stale PIDs auto-detected via `kill -0` probe before spawning a new instance — no orphaned processes.

**Content-based drift, not mtime**: `touch` on a source file does NOT trigger a tick. Only actual content changes do (the `dir_hash` function hashes file contents, deterministic order). This eliminates false positives from `git status` / editors that bump mtime without writing.

**Initial tick on startup**: when the watcher starts, it immediately runs a full tick to catch any drift accumulated while offline. Subsequent ticks fire only on hash mismatch.

### Combined with cron

| Mode | Trigger | Latency | Resource |
|---|---|---|---|
| `daemon install` (cron) | every 30 min | up to 30 min | zero between ticks |
| `daemon watch-start` (watcher) | hash-poll every 5 s | 5 s | sleeping process |
| Both | redundant safety | min(5s, 30min) | watcher process + cron |

Running both is safe; both are idempotent.

### Bugfix

- daemon.py was missing top-level `asyncio` + `signal` imports (caught at watch-start time on first try). Fixed.

## [1.5.1] — 2026-05-11

### Docs — clarify daemon vs. CC's built-in `autoUpdate`

Trace surfaced that Claude Code already has a per-marketplace `autoUpdate: true` flag (in `~/.claude/settings.json` → `extraKnownMarketplaces.<name>.autoUpdate`), and your `kaizen-md` entry already has it on. So the daemon's hash-compare refresh-cache step partially overlaps with CC's session-start refresh.

**No code change** — the daemon stays as designed. CC's `autoUpdate` covers session-start; daemon covers mid-session + hygiene. Both rsync source→cache idempotently; running both is safe.

**Updated docs**:

- `commands/daemon.md` — adds a "Relationship to Claude Code's built-in autoUpdate" table showing which capability comes from which layer (session-start = CC, mid-session + prune + retention + validation = daemon).
- `plugin-pitfalls` #15 — documents the autoUpdate session-start-only timing window, with the failure symptom ("pushed v1.4.1, /plugin update says done, but command still missing") that triggered the trace.

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
