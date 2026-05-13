> **SUPERSEDED 2026-05-13** — plan files no longer live in the plugin
> source dir. Canonical location: `~/workspace/shodan/plans/2026-05-13-kaizen-roadmap.md`.
> This stub stays for back-compat (the file appeared in HEAD at commits
> 1a48698 / 34dd65b / c896df9); for live content read the canonical.

# Kaizen roadmap — multi-axis semantic + workspace-discipline upgrade

- **Date:** 2026-05-13
- **Status:** initial — not actioned. Phases ship independently.
- **Method:** traced existing surfaces in `plugins/kaizen/` + shodan `xtask/`; identified gaps + extractable tools; designed phases.
- **Scope:** five axes (A/B/C/X/M) covering embedding pipeline, onboard quality, scraper/crawl, workspace-discipline tools extracted from xtask, and MCP tooling growth.
- **Proven primitive:** shodan's `xtask loc` was upgraded in commit `04af201` (2026-05-13) to function-level AST extraction via syn — 100% accurate line ranges + McCabe cyclomatic complexity per function. That commit demonstrates the X1 pattern that this roadmap ports to kaizen.

## TL;DR

Kaizen has 5 SQLite-backed indexes (knowledge / onboard / trace / scrape / claude-docs), 9 MCP servers (67 tools), 30 bin CLIs, and 12-check pre-commit gate. The next wave of upgrades touches **five orthogonal axes**:

| Axis | Surface | Scope |
|---|---|---|
| **A.** Embedding pipeline (`_embed.py` / `_chunk.py`) | shared across all 5 indexes | model-aware prefixes, cross-encoder rerank, multilingual, quantization, matryoshka, static models, multi-process |
| **B.** Onboard quality (`onboard_index.py`) | code semantic search | preserve docstrings, AST chunking, metadata prefix, smarter summary, xref table, symbol routes |
| **C.** Scraper / crawl (`scrape_index.py`) | web content | full-site crawl, robots/sitemap, resume, link graph, async, canonical URLs |
| **X.** Workspace-discipline tools | from shodan xtask | function-level loc, drift detector, multi-language manifests, code-lift engine, composite hygiene |
| **M.** MCP tooling | exposes everything above | +new servers (loc / drift / manifests / shim) + extensions to existing servers |

Each axis is shippable independently. The order below is **maximum-leverage first**.

---

## Axis A — Embedding pipeline upgrades

Touches `skills/workflow/scripts/_embed.py` + `_chunk.py`. Every indexer benefits.

| # | Feature | Source | Effort | Win |
|---|---|---|---|---|
| **E1** | Model-aware asymmetric prefixes — detect `nomic` / `bge` / `e5` / `jina` / `gte-qwen` and apply each model's expected query/passage prefix. Currently both are hard-coded `search_query: ` / `search_document: `. | ST docs | S | Higher recall on every search. |
| **E2** | Cross-encoder reranking — after hybrid RRF, rerank top-K with `cross-encoder/ms-marco-MiniLM-L-6-v2` or `BAAI/bge-reranker-base`. Optional via `--rerank` flag + `KAIZEN_RERANK_MODEL`. | ST `CrossEncoder` | M | +50-200ms/query but materially better precision@1. |
| **E3** | Multilingual models — auto-pick `paraphrase-multilingual-MiniLM-L12-v2` when content language ≠ English (langdetect on the chunk). | ST multilingual | M | Required for non-English code comments / docs. |
| **E4** | Binary + int8 quantization — `embedding_bin` BLOB (1 bit per dim → 48 bytes for 384-dim, 32× smaller than float32). Two-stage retrieve: binary shortlist → int8 rerank → float32 final. Current state has `embedding_q8` (int8); binary is the next tier. | ST `quantize_embeddings()` | M | Drastic disk + cosine-scan speed on large indexes. |
| **E5** | Matryoshka embeddings — load matryoshka-trained models (`mixedbread-ai/mxbai-embed-large-v1` 1024-dim → 512 / 256 / 64 truncations). Coarse-to-fine retrieval. | ST matryoshka | M-L | Faster shortlist + smaller index without retraining. |
| **E6** | Static embeddings (model2vec) — no-GPU, no-torch path (~1 MB model). Cross-CLI parity on hosts without torch. | model2vec | S | Required for Codex / shell-only hosts. |
| **E7** | Multi-process encoding — `encode_multi_process` for batches > 500 chunks. | ST | S | 4-8× faster initial reindex. |
| **E8** | L2 + pooling knobs — `KAIZEN_EMBED_NORMALIZE=l2`, `KAIZEN_EMBED_POOLING=mean\|cls\|max`. | ST `Pooling` | S | Per-use-case tuning. |
| **E9** | Sparse encoding (SPLADE) — `naver/splade-cocondenser-ensembledistil` for learned sparse. Stored in `*_sparse` table. | ST sparse | L | Tier 3 — beats BM25 on OOV. |
| **E10** | ColBERT-style late interaction — token-level multi-vector. Storage ~30× dense; precision win. | ST ColBERT | L | Tier 3. |

## Axis B — Onboard quality

Touches `skills/workflow/scripts/onboard_index.py`.

| # | Feature | Effort |
|---|---|---|
| **O1** | Preserve docstrings as a sidecar signal — keep current code cleaning, but ALSO extract docstrings/header-comments per chunk; embed both. Closes "why" queries. | M |
| **O2** | Symbol-aware chunking (Python AST first) — use `ast.parse` to find function/class boundaries; never split inside a function unless > 512 tokens. Add `symbol_name` column. Python = 60%+ of kaizen-md index. | M |
| **O3** | Metadata-rich passage prefix — prepend `file: <path>\nlanguage: <lang>\nsymbol: <name>\n` to each passage before embedding. ~30 tokens per chunk; embedding learns provenance. | S |
| **O4** | Tiny-chunk merging — chunks < 200 chars collapse into neighbor. | S |
| **O5** | Smarter file-level summary — replace "first 2KB" with concatenated class/function signatures + first docstring line. Same budget, higher signal density. | S |
| **O6** | Imports/exports xref table — `code_chunks_xref(chunk_id, symbol, kind=import\|def\|call)`. Enables "find chunks that import X" / "who calls Y" queries. | M |
| **O7** | Per-symbol search route — `kaizen-onboard search --symbol foo`. Depends on O2. | S |
| **O8** | Tree-sitter universal chunker — replaces O2's Python-only with uniform 18-language AST. Adds 1 dep (~30 MB single wheel). | L |

## Axis C — Scraper / crawl

Touches `skills/workflow/scripts/scrape_index.py` + new crawler module.

| # | Feature | Effort |
|---|---|---|
| **S1** | `kaizen-scrape crawl <start_url>` — BFS link walk. Flags: `--depth N` (2), `--max-pages N` (100), `--include-subdomains`, `--rate-limit MS` (500), `--allow-pattern REGEX`, `--block-pattern REGEX`. | M-L |
| **S2** | robots.txt + sitemap.xml — respect crawl rules; prefer sitemap when available. | M |
| **S3** | Resume / incremental — `scrape_urls(canonical_url PK, last_scraped, sha)`. Skip URLs scraped within `--max-age-days N`. | S |
| **S4** | Link graph table — `scrape_links(parent_url, child_url, anchor_text)`. Enables "doc tree" + "what links to X". | S |
| **S5** | HEAD pre-check — `requests.head()` before `.get()`. Skip non-HTML content types + redirect chains. | S |
| **S6** | Canonical URL normalization — strip fragments, normalize trailing slash, lowercase host, sort query params. | S |
| **S7** | Per-host concurrency — async fetch with `--concurrency N` (4). Honors `--rate-limit` per-host. | M |
| **S8** | Sitemap export — `kaizen-scrape sitemap <host>` prints the crawled link tree as YAML / DOT. | S |

## Axis X — Workspace-discipline tools (extracted from shodan xtask)

xtask's 14 subcommands gap-checked against kaizen. Already in kaizen: `docs`, `rules` (ast-grep), `hygiene` (lighter), `migrate-paths` (path rewriter only). **5 new extractions follow.**

| # | Tool | Slash command | Source | Effort | Notes |
|---|---|---|---|---|---|
| **X1** | **Codebase metrics analyzer (function-level)** | `/kaizen:loc` | `xtask/src/loc.rs` ([04af201](shodan/04af201) demonstrates the upgrade pattern) | M | God-file tiers (Warning 500-1000, Critical >1000), per-language summary, **per-function AST extraction** with exact line ranges + McCabe cyclomatic. Searchable SQLite (`loc.db`). New table: see X1 schema below. |
| **X2** | **Structural-drift detector** | `/kaizen:drift` | `xtask/src/drift/mod.rs` (~270 LOC) | M | Consumes `docs/crates/*.json` from `/kaizen:docs --json`. Baseline at `.kaizen/workflow/drift-baseline/`. Reports added/removed/renamed public items + dep deltas + LOC swings. `--record` seeds; `--fail-on-drift` gates CI (§ADV-6 pattern just landed in shodan). |
| **X3** | **Multi-language manifest hygiene** | `/kaizen:manifests` (audit / promote / unused) | `xtask/src/manifests.rs` (Cargo-only) | M-L | Generalize to Cargo.toml + package.json + pyproject.toml + go.mod. Per-language adapters; same orchestrator. |
| **X4** | **Code-lift engine + import rewriter** | `/kaizen:migrate carve` (audit / preview / deps-gap / lift) | `xtask/src/migrate/{audit,preview,deps_gap,lift,rewriter}.rs` (~700 LOC) | L | Reads project-local `kaizen-migrations.toml`. Completes the shim-and-sweep tooling story: `kaizen-shim carve` handles file-level shim; `/kaizen:migrate carve` handles workspace-level structural moves with import rewriting. Rust first; Python second via stdlib `ast`. |
| **X5** | **Composite hygiene** | `/kaizen:hygiene check` extension | `xtask/src/hygiene.rs` | S-M | Per-language composite: Rust = manifests + cargo audit + toolchain; Python = pyproject + pip-audit; TS = package.json + npm audit. CI-gateable exit-non-zero contract. |

### X1 — `/kaizen:loc` schema (function-level)

```sql
CREATE TABLE loc_symbols (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  path              TEXT NOT NULL,
  language          TEXT NOT NULL,
  symbol_kind       TEXT NOT NULL,  -- function | method | assoc-fn | trait-fn |
                                      -- class | impl | struct | enum | trait |
                                      -- const | macro | module
  symbol_name       TEXT NOT NULL,
  qualified_name    TEXT NOT NULL,  -- "Mod::Type::method" / "Class.method"
  parent_symbol     TEXT,            -- enclosing scope name
  line_start        INTEGER NOT NULL,  -- 1-indexed, inclusive
  line_end          INTEGER NOT NULL,
  col_start         INTEGER,
  col_end           INTEGER,
  byte_start        INTEGER NOT NULL,
  byte_end          INTEGER NOT NULL,
  physical_lines    INTEGER NOT NULL,
  logical_lines     INTEGER,
  cyclomatic        INTEGER,          -- McCabe (Rust: AST; Python: AST; other: NULL)
  cognitive         INTEGER,          -- Sonar-style (future)
  nesting_depth     INTEGER,
  has_docstring     INTEGER NOT NULL,
  is_test           INTEGER NOT NULL,
  is_async          INTEGER NOT NULL,
  is_public         INTEGER NOT NULL,
  signature         TEXT,             -- "def carve(old, new, slug, *, reexport=None)"
  signature_hash    TEXT,             -- detect renames
  body_sha          TEXT NOT NULL,
  parser            TEXT NOT NULL,    -- "ast" (Python stdlib) | "syn" (Rust) | "tree-sitter" | "regex"
  updated_at        TEXT NOT NULL,
  UNIQUE(path, line_start, symbol_name)
);
CREATE INDEX idx_loc_path     ON loc_symbols(path);
CREATE INDEX idx_loc_lang     ON loc_symbols(language);
CREATE INDEX idx_loc_kind     ON loc_symbols(symbol_kind);
CREATE INDEX idx_loc_lines    ON loc_symbols(physical_lines DESC);
CREATE INDEX idx_loc_complex  ON loc_symbols(cyclomatic DESC);
CREATE INDEX idx_loc_name     ON loc_symbols(symbol_name);
CREATE INDEX idx_loc_qname    ON loc_symbols(qualified_name);
CREATE INDEX idx_loc_range    ON loc_symbols(path, line_start, line_end);

CREATE TABLE loc_files (
  path              TEXT PRIMARY KEY,
  language          TEXT NOT NULL,
  physical_lines    INTEGER NOT NULL,
  logical_lines     INTEGER NOT NULL,
  comment_lines     INTEGER NOT NULL,
  blank_lines       INTEGER NOT NULL,
  symbol_count      INTEGER NOT NULL,
  test_symbol_count INTEGER NOT NULL,
  god_tier          TEXT,             -- 'critical' | 'warning' | NULL
  max_function_lines INTEGER NOT NULL,
  comment_density   REAL NOT NULL,
  sha               TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE TABLE loc_meta (key TEXT PRIMARY KEY, value TEXT);
```

### X1 — parser tier table

| Language | Parser | Accuracy | Notes |
|---|---|---|---|
| Python | `ast` (stdlib) | **100%** | Authoritative — `ast.get_source_segment` + `node.lineno` / `end_lineno`. |
| Rust | `syn 2.0` + `proc-macro2` span-locations | **100%** | Already proven in shodan `xtask/src/loc.rs::extract_rust_functions` (commit 04af201). |
| JS / TS / Go / C / C++ / Java / Kotlin / Scala / Swift / C# / PHP / Ruby / Lua / SQL / Bash | `tree-sitter-<lang>` | **100%** when installed | Optional dep via `tree-sitter-languages` bundle (~50 MB, 30+ grammars). |
| anything else | regex fallback | ~85% | Carries `parser: 'regex'` flag so consumers can verify or skip. |

### X1 — CLI surface

```bash
# Indexing
kaizen-loc index [--root <path>] [--incremental]
kaizen-loc reindex
kaizen-loc stats [--by language|kind]
kaizen-loc path

# Symbol-level search
kaizen-loc search --name carve
kaizen-loc search --name '*shim*'                  # glob
kaizen-loc search --qualified 'CodexExporter.export_skills'
kaizen-loc search --kind function --min-lines 100 --max-lines 500
kaizen-loc search --complexity '>=15'
kaizen-loc search --no-tests
kaizen-loc search --god critical
kaizen-loc search --at <file>:<line>               # what function is this line in?

# File-level
kaizen-loc files --god critical
kaizen-loc files --comment-density '<0.05'
kaizen-loc files --max-fn-lines '>200'

# Source extraction
kaizen-loc show <id>                                # prints exact byte range
kaizen-loc show <id> --json                         # structured

# Verdict (the xtask report view)
kaizen-loc report
kaizen-loc report --json
```

## Axis M — MCP tooling

Current state: 67 MCP tools across 9 servers. Adding 3 servers + extending 2 existing.

| # | Server / extension | Tools | Effort |
|---|---|---|---|
| **M1** | **`loc` MCP** (new) | `loc_search`, `loc_function_at(file, line)`, `loc_god_symbols(tier)`, `loc_stats(by=)`, `loc_files`, `loc_show(id)`, `loc_index_run` | M |
| **M2** | **`drift` MCP** (new) | `drift_status`, `drift_record_baseline`, `drift_check(fail_on_drift=False)`, `drift_explain(crate=)` | S |
| **M3** | **`manifests` MCP** (new) | `manifests_audit`, `manifests_unused`, `manifests_promote(apply=False)`, `manifests_languages` | M |
| **M4** | **Rerank extension** — every search MCP gains `rerank=True` param; new ad-hoc tool `embed_rerank(query, candidates[])`. | M |
| **M5** | **Structured output everywhere** — every MCP tool returns typed JSON (Pydantic models). Standardizes the mixed-shape return values. | M |
| **M6** | **Scrape crawl extension** — `scrape_crawl(start_url, depth, max_pages, include_subdomains)`, `scrape_sitemap(host)`, `scrape_links(parent_url)`. | S |
| **M7** | **Onboard symbol-search extension** (after O2) — `onboard_symbol_search(name, kind)`, `onboard_xref(symbol, direction=callers\|callees)`. | S |
| **M8** | **`shim` MCP** (new) — surfaces existing `kaizen-shim` CLI. `shim_init(slug)`, `shim_carve(old, new, slug, reexport=)`, `shim_list(slug)`, `shim_sweep(slug, allow_delete=False, dry_run=True)`. | S |
| **M9** | **`kaizen-discipline` composite MCP** — proxies queries across loc + drift + manifests + lint for "what should I clean next" workflows. | M |

**Result: 67 → 110+ MCP tools when M1-M9 land.**

---

## Compat lens (constraints applied to every item)

Per the cross-CLI portability work (R1+R2+R3, kaizen-export to Codex):

- **No removal of existing kaizen surfaces.** All additions are additive layers.
- **CC-only primitives** (`AskUserQuestion`, `ExitPlanMode`, `TaskCreate`, `SubagentStop`/`SessionEnd`/`Notification` hooks) are wired as ENRICHMENTS — present when CC is host, silently absent on Codex.
- **CC-specific hooks live in `hooks/claude/`** per the provider-categorized layout (R-PROV — 2026-05-13).
- **Cross-CLI portability via `kaizen-export --target codex`** — every new MCP tool reachable from there.
- **Embedding dependency profile** — workspace already requires `sentence-transformers + torch`; E6 (model2vec) is the *only* dep-free path for Codex / minimal hosts.

---

## Sequencing — independent phases

### Phase 1 — instant quality wins + first extracted tool (~900 LOC)

| # | Item | Surface |
|---|---|---|
| O1 | Preserve docstrings | onboard |
| O3 | Metadata-rich passage prefix | onboard |
| E1 | Model-aware prefix detection | shared embed |
| E7 | Multi-process encoding | shared embed |
| E8 | Pooling / normalize knobs | shared embed |
| S1 + S2 + S3 | Crawl basics | scraper |
| **X1** | **Function-level loc** (port from shodan 04af201) | new `/kaizen:loc` |
| **M1** | loc MCP server | new |
| **M8** | shim MCP server | new (surfaces existing kaizen-shim CLI) |

No new dependencies. Each item independently testable + commitable.

### Phase 2 — discipline tools + retrieval quality (~1000 LOC)

| # | Item |
|---|---|
| X2 | `/kaizen:drift` + M2 drift MCP |
| X5 | hygiene composite (per-language) |
| E2 | Cross-encoder rerank + M4 rerank in every search MCP |
| E4 | Binary quantization (all indexers) |

### Phase 3 — heavier discipline + structural quality (~1400 LOC)

| # | Item |
|---|---|
| X3 | `/kaizen:manifests` + M3 manifests MCP |
| O2 + O5 + O6 | AST chunking + smart summary + xref + M7 symbol-search |
| E5 | Matryoshka embeddings |

### Phase 4 — speculative / opt-in

| # | Item |
|---|---|
| X4 | `/kaizen:migrate carve` (full code-lift engine) |
| E6 | model2vec — cross-CLI parity for non-torch hosts |
| E9 | SPLADE — learned sparse |
| E10 | ColBERT — late interaction |
| O8 | Tree-sitter universal chunker |
| S6 + S7 + S8 | URL canonicalization + async + sitemap export + M6 scrape_crawl MCP |
| M5 | Structured output everywhere (Pydantic shapes for every MCP tool) |
| M9 | `kaizen-discipline` composite MCP |

---

## Acceptance criteria — Phase 1

- [ ] `python3 -m unittest discover -s tests` passes (currently 293; expect ~340 after Phase 1).
- [ ] `kaizen-loc index` runs cleanly on the kaizen-md repo + indexes ≥ all Python + bash + yaml + ts files.
- [ ] `kaizen-loc search --name 'carve'` returns the `kaizen-shim::carve` function with line range matching `git blame`.
- [ ] `kaizen-loc search --at scripts/shim.py:200` returns the enclosing function for that line.
- [ ] `mcp__plugin_kaizen_loc__loc_function_at(...)` returns the same record.
- [ ] `kaizen-scrape crawl https://www.sbert.net --max-pages 30` completes; `scrape_links` table populated; `scrape_stats` shows ≥ 30 items.
- [ ] `kaizen-onboard search 'carve a file into a new location'` returns the `shim.py::carve` chunk at top (currently noisy due to no docstring preservation).
- [ ] All hooks still fire correctly per `tests/test_cc_hooks_wireup.py` (no regression on the provider-categorization).

## Reference commits + proven primitives

| Commit | Provides |
|---|---|
| shodan `04af201` (2026-05-13) | Reference implementation of X1 — `syn`-based function-level extraction with cyclomatic complexity in xtask. Port pattern to Python via stdlib `ast`. |
| kaizen `5c1be04` (2026-05-13) | shim-and-sweep routine — discipline doc + schema; X1 + M1 makes its "find god functions" use case concrete. |
| kaizen `3519c87` (2026-05-13) | `kaizen-shim` CLI — what M8 surfaces via MCP. |
| kaizen `9e99307` (2026-05-13) | hook categorization by provider — establishes the layout for adding CC-only enrichments in `hooks/claude/`. |
| kaizen `3fc687a` (2026-05-13) | `arch-log` source in knowledge_index — pattern to copy when adding new index sources. |

## Out of scope

- **Training / fine-tuning** — kaizen consumes embeddings, doesn't train them. ST training utilities not exposed.
- **GUI** — kaizen is CLI + MCP. No web UI.
- **Cross-repo aggregation** — each repo has its own `.kaizen/onboard.db`. Federated search is a future axis.
- **Plugin marketplace mechanics** — `/plugin update`, marketplace discovery — covered by CC native + existing `/kaizen:update`.

## Next step

Phase 1, item X1 first — port shodan's `xtask/src/loc.rs::extract_rust_functions` to Python via stdlib `ast` + create the `loc.db` SQLite schema above + ship `bin/kaizen-loc` + M1 MCP wrapper. Tests cover the same 17 cases as the Rust reference.

After X1+M1 lands, the rest of Phase 1 (O1/O3/E1/E7/E8/S1-S3/M8) follows in a single PR.
