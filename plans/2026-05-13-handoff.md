> **SUPERSEDED 2026-05-13** — plan files no longer live in the plugin
> source dir. Canonical location: `~/workspace/shodan/plans/2026-05-13-handoff.md`.
> This stub stays for back-compat (the file appeared in HEAD at commits
> 1a48698 / 34dd65b / c896df9); for live content read the canonical.

# Handoff — kaizen roadmap (commit 34dd65b)

> Read this first if you're a fresh session picking up the kaizen
> roadmap. It names the files to load in order so you can start
> executing without re-tracing prior decisions.
>
> **Two repos involved.** The kaizen plugin lives in
> `~/.claude/local-marketplaces/kaizen-md/` (this file's home) — that's
> where Phase 1 ships. The shodan workspace (`~/workspace/shodan/`)
> hosts the X1 reference impl (`xtask/src/loc.rs`, commit `04af201`)
> that Phase 1 ports to Python.
>
> If you invoked `/kaizen:workflow continue plans/2026-05-13-handoff.md`
> from shodan's cwd and hit a "file not found", `cd
> ~/.claude/local-marketplaces/kaizen-md` first. A forwarder exists at
> `~/workspace/shodan/plans/2026-05-13-handoff.md` pointing here.

## State at handoff

- **HEAD:** `34dd65b` — `docs(plans): kaizen roadmap — 5-axis semantic + discipline upgrade`
- **What just landed:** the multi-axis roadmap `plans/2026-05-13-kaizen-roadmap.md`. Five orthogonal axes (A/B/C/X/M); 5 phases scheduled; no implementation in this commit, just the durable plan.
- **Proven primitive:** the X1 pattern (function-level AST extraction via syn) was implemented + tested in shodan workspace at commit `04af201`. The Python port for kaizen reuses that pattern via stdlib `ast`.
- **Compat lens:** every addition is additive (no kaizen feature removal); CC-only primitives wired as silent-no-op on Codex; new CC-side hooks live under `hooks/claude/`.
- **Test baseline:** 293 unittest tests pass, 2 pre-existing errors (`test_backlog` + `test_chunk` path drift, unrelated).

## Reading order

### Tier 1 — must read before touching code

1. **`plans/2026-05-13-kaizen-roadmap.md`** — THE plan. 5 axes, 50+ enumerated items, Phase 1-4 sequencing, full SQLite schema for `loc.db` (X1), 8 acceptance criteria.
2. **`plans/2026-05-13-cross-cli-portability-analysis.md`** — the constraints. Why we categorize hooks by provider; why kaizen surfaces stay canonical; the R1+R2+R3 work that unblocked cross-CLI.
3. **`CLAUDE.md`** (global at `~/.claude/CLAUDE.md`) — discipline rules: GAB, no-deletions belief, compile barrier, pre-commit gate, plan-file vs backlog sizing.

### Tier 2 — read before Phase 1 X1 (loc port)

4. **`/home/cherry86/workspace/shodan/xtask/src/loc.rs`** — reference implementation. Read `FnVisitor`, `ComplexityVisitor`, `compute_complexity`, `extract_rust_functions`. The Python port mirrors this shape using stdlib `ast`.
5. **`plugins/kaizen/skills/workflow/scripts/knowledge_index.py`** — the indexer pattern X1 follows. SQLite schema (lines 43-60), `iter_*` source generators (line 239+), `item_sha` identity (line 410), incremental indexing (line 700+).
6. **`plugins/kaizen/skills/workflow/scripts/knowledge_mcp.py`** — pattern for M1 MCP server. FastMCP setup, `@mcp.tool()` decorators, signature + return types.
7. **`plugins/kaizen/tests/test_knowledge_arch_log.py`** — the 1:1 test pattern. Set-up via tmpdir + cwd swap, assertions on item shape + iteration. X1 tests follow the same form.

### Tier 3 — read when starting other Phase 1 items

8. **`plugins/kaizen/skills/workflow/scripts/_chunk.py`** — chunker for O1/O3 (preserve docstrings + metadata-rich passage prefix). `QUERY_PREFIX` / `PASSAGE_PREFIX` (line 178), `apply_passage_prefix` (line 191).
9. **`plugins/kaizen/skills/workflow/scripts/_embed.py`** — embedder for E1 (model-aware prefixes) / E7 (multi-process) / E8 (pooling). Backend resolution (line 188), local model load (line 264).
10. **`plugins/kaizen/skills/workflow/scripts/onboard_index.py`** — the file O1 + O3 modify. `clean_for_embed` (line 503), `chunk_record` (line 518), passage-prefix application (line 728).
11. **`plugins/kaizen/skills/workflow/scripts/scrape_index.py`** — the file S1/S2/S3 extend. Current state: one URL at a time.

### Tier 4 — read for cross-cutting context

12. **`plugins/kaizen/skills/shim-and-sweep/SKILL.md`** — the routine M8 surfaces. 5 Iron Laws, per-language shim shapes, pre-commit-gate cooperation. Already-shipped tooling (`kaizen-shim` CLI).
13. **`plugins/kaizen/skills/workflow/scripts/shim.py`** — what M8 MCP server wraps. Pure module surface (`manifest_init`, `carve`, `sweep`).
14. **`plugins/kaizen/hooks/README.md`** — provider-categorized hooks layout. New CC-only enrichments land under `hooks/claude/`; future Codex hooks under `hooks/codex/`.
15. **`plugins/kaizen/bin/kaizen-shim`** — the bin wrapper pattern. Sources `_plugin_root.sh`, execs the script. New `bin/kaizen-loc` mirrors this.
16. **`plugins/kaizen/skills/workflow/scripts/_plugin_root.sh` / `_plugin_root.py`** — resolver every new script + bin uses. CLAUDE_PLUGIN_ROOT → KAIZEN_PLUGIN_ROOT → derived.

## Quick orientation

### What's already in place (don't reinvent)

| Surface | Status | Path |
|---|---|---|
| 67 MCP tools across 9 servers | live | `skills/workflow/scripts/*_mcp.py` |
| 30 bin CLIs (`kaizen-*`) | symlinked to `~/.local/bin/` | `bin/` |
| 12-check pre-commit gate | enforced | `skills/workflow/scripts/pre-commit.sh` |
| Knowledge index (arch-log included) | live | `~/.claude/.kaizen/knowledge/index.db` |
| Onboard index (kaizen-md repo) | live | `<repo>/.kaizen/onboard.db` |
| Trace index (3,756 events) | live | `~/.claude/.kaizen/trace/index.db` |
| Scrape index (sbert.net) | live | `~/.claude/.kaizen/scrape/index.db` |
| Hooks split by provider | live | `hooks/claude/*.sh` + `hooks/hooks.json` (canonical CC discovery path) |
| `kaizen-shim` CLI for shim-and-sweep | live | `bin/kaizen-shim` |
| Cross-CLI export | live | `bin/kaizen-export --target codex` |

### Key invariants

- **Plan files** go under `plans/<date>-<slug>.md` per shodan's CLAUDE.md convention. Pre-commit gate accepts these as the "plan-file mention" signal.
- **No deletion mid-refactor** — `pre_deletion_belief` gate blocks `git rm` without `KAIZEN_ALLOW_DELETE=1` + brain-belief authorization. Use shims instead.
- **Architecture-log rows** — only required for shodan repo's CLAUDE.md; kaizen-md doesn't currently enforce this.
- **Tests live in `plugins/kaizen/tests/test_*.py`** discoverable via `python3 -m unittest discover -s tests`. Each new module gets `tests/test_<module>.py`.
- **Embedding model resolution** is host-aware: local SentenceTransformer by default; `KAIZEN_EMBED_BACKEND=http` + `KAIZEN_EMBED_HTTP_BASE_URL` + `KAIZEN_EMBED_HTTP_MODEL` routes to Ollama. Don't hard-code 384-dim; read from meta table.
- **Cross-CLI compat:** scripts can use bash + python3 + kaizen helpers; must not invoke `claude` CLI or other CC-only binaries inside script bodies. `test_cc_hooks_wireup.py::TestCrossCliCompatProfile` enforces this.

### Where to start — Phase 1, item X1

**File to create:** `plugins/kaizen/skills/workflow/scripts/loc_index.py`

**Mirror:** `skills/workflow/scripts/knowledge_index.py` (~700 LOC reference) for the SQLite + indexer + CLI pattern.

**Port:** the `extract_rust_functions` from `xtask/src/loc.rs` to Python using stdlib `ast`. Map node types:

| Rust (syn) | Python (ast) |
|---|---|
| `syn::ItemFn` | `ast.FunctionDef`, `ast.AsyncFunctionDef` (top-level) |
| `syn::ImplItemFn` | `ast.FunctionDef` inside `ast.ClassDef` |
| `syn::TraitItemFn` | — (no Python equivalent; treat protocol/abstract methods as `ast.FunctionDef` with `@abstractmethod`) |
| `syn::ExprIf` | `ast.If` |
| `syn::ExprMatch` | `ast.Match` (Python 3.10+) |
| `syn::ExprWhile/For/Loop` | `ast.While`, `ast.For` |
| `syn::BinOp::And/Or` | `ast.BoolOp` with `ast.And`/`ast.Or` |
| `syn::ExprTry` | — (no Python equivalent; skip) |
| `syn::ExprClosure` | `ast.Lambda` |

Line numbers from `ast.AST.lineno` + `ast.AST.end_lineno` (Python 3.8+) are 1-indexed inclusive — identical to syn's `span-locations`.

**SQLite schema:** copy from `plans/2026-05-13-kaizen-roadmap.md` § X1 verbatim.

**Bin wrapper:** copy `bin/kaizen-shim` shape → `bin/kaizen-loc`.

**MCP server:** copy `skills/workflow/scripts/knowledge_mcp.py` shape → `loc_mcp.py`. 7 tools per the roadmap's M1.

**Tests:** mirror `xtask/src/loc.rs::tests` — same 17 cases, Python-shaped. Plus integration tests for SQLite round-trip + MCP tool shapes.

### Acceptance for Phase 1 X1 (from roadmap)

- [ ] `python3 -m unittest discover -s tests` passes (293 → ~310).
- [ ] `kaizen-loc index` runs cleanly on the kaizen-md repo + indexes all `*.py` + `*.sh` + `*.yaml` + `*.ts` + `*.js` files.
- [ ] `kaizen-loc search --name 'carve'` returns the `kaizen-shim::carve` function with line range matching `git blame plugins/kaizen/skills/workflow/scripts/shim.py | head`.
- [ ] `kaizen-loc search --at scripts/shim.py:200` returns the enclosing function for that line.
- [ ] `mcp__plugin_kaizen_loc__loc_function_at(file=..., line=...)` returns the same record.

## Phase 1 — full punch list (after X1+M1 lands)

| # | Item | File(s) | Status |
|---|---|---|---|
| X1 | function-level loc | new `loc_index.py` + `loc_mcp.py` + `bin/kaizen-loc` | **start here** |
| M1 | loc MCP server | `loc_mcp.py` | bundled with X1 |
| M8 | shim MCP server | new `shim_mcp.py` | small — wraps `shim.py` |
| O1 | preserve docstrings | `onboard_index.py::clean_for_embed` | after X1 |
| O3 | metadata-rich passage prefix | `onboard_index.py` + `_chunk.py` | after X1 |
| E1 | model-aware prefix detection | `_chunk.py::QUERY_PREFIX/PASSAGE_PREFIX` + `_embed.py` | after O3 |
| E7 | multi-process encoding | `_embed.py` | independent |
| E8 | pooling / normalize knobs | `_embed.py` | independent |
| S1 | crawl subcommand | `scrape_index.py` | independent |
| S2 | robots.txt + sitemap.xml | `scrape_index.py` | after S1 |
| S3 | resume / incremental | `scrape_index.py` | after S1 |

## Useful commands

```bash
# Find prior commits referenced in the roadmap
git log --oneline --grep "X1\|loc.rs\|kaizen-shim\|shim-and-sweep\|provider"

# Read the live progress.md (kaizen-md doesn't have one; shodan does)
cat /home/cherry86/workspace/shodan/.kaizen/workflow/progress.md

# Query the knowledge index for arch-log rows
uv run --script ~/.claude/local-marketplaces/kaizen-md/plugins/kaizen/skills/workflow/scripts/knowledge_index.py search "<keyword>"

# Smoke the shodan reference (works on shodan repo, not kaizen-md)
cd /home/cherry86/workspace/shodan && cargo run -q -p xtask -- loc 2>&1 | sed -n '/Function-Level/,/Multi-Tier/p'

# Run kaizen-md test suite
cd /home/cherry86/.claude/local-marketplaces/kaizen-md/plugins/kaizen && \
  python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
```

## Reference commits

| Commit | Repo | Purpose |
|---|---|---|
| `04af201` | shodan | X1 reference impl — syn-based function-level extraction |
| `34dd65b` | kaizen-md | the roadmap doc (this handoff describes this commit) |
| `5c1be04` | kaizen-md | shim-and-sweep routine (relates to M8) |
| `3519c87` | kaizen-md | `kaizen-shim` CLI (what M8 surfaces) |
| `9e99307` | kaizen-md | provider-categorized hooks layout |
| `3fc687a` | kaizen-md | `arch-log` source in knowledge_index (pattern to copy for X1) |
| `1a48698` | kaizen-md | cross-CLI portability analysis (compat constraints) |
| `1ac7cb5` | kaizen-md | `kaizen-export --target codex` (R3 portability anchor) |

## Open questions for the next session

1. **Tree-sitter dep budget** — bundling tree-sitter-languages (~50 MB single wheel covering 30+ grammars) for X1 / O8 is convenient but adds weight. Worth it for kaizen-md's audience? Phase 4 deferred this; revisit after X1's Python AST coverage proves the value.
2. **Quantization tier ordering** — E4 (binary + int8 two-stage retrieval) before or after E2 (cross-encoder rerank)? They compose. Cross-encoder works on top of binary shortlist; recommend E4 then E2.
3. **Per-repo vs user-global `loc.db`** — X1 schema is per-repo (parallels onboard.db). Consider also a user-global `loc.db` summing across multiple repos? Defer until multi-repo demand surfaces.
