# Coverage-loop implemented — 30 ideas across 3 iterations

- **Date:** 2026-05-18
- **Loop session:** `/kaizen:tdd run until completion yagni stored as deferred execute writing-plans`
- **Source brainstorm:** `~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl` (300 ideas)
- **Pick rule:** `status=top-pick OR tier∈{1,2}` first, sorted by tier asc then id asc
- **Test baseline:** 3080 → 3153 (+73 tests, 0 regressions, 79 skipped)
- **Commits this run:** 30 feature + 1 Boy-Scout rename

Each idea ships as a paired `script + test + bin + plugin.json perm` quartet. Graceful-skip for external deps (vulture / radon / duckdb / ollama) per `pref-optional-feature-graceful-fallback`.

## Iter 1 — wiring + observability + dep-wrapper axes

- [x] **#34** `kaizen-perm-coverage` — every argparse-main script has a `plugin.json` perm entry
- [x] **#35** `kaizen-hook-coverage` — orphan + missing detection for `hooks/hooks.json` wiring
- [x] **#36** `kaizen-bin-coverage` — every argparse-main script has a `bin/kaizen-*` wrapper
- [x] **#37** `kaizen-command-allowed-tools-coverage` — `commands/*.md` declares `allowed-tools:` frontmatter
- [x] **#38** `kaizen-mcp-coverage` — every `*_mcp.py` is mounted in gateway `SUBSERVERS`
- [x] **#22** `kaizen-sandbox-check` (was test-isolation) — AST scan for sandbox violations (hardcoded `/home/`, `os.environ["KAIZEN_*"]=...`, `~/.claude/...`)
- [x] **#3** `kaizen-dead-code` — vulture wrapper, graceful-skip when not installed
- [x] **#216** `kaizen-complexity` — radon cc wrapper, graceful-skip
- [x] **#201** `kaizen-sql` — DuckDB ad-hoc query over JSONL, graceful-skip
- [x] **#141** `kaizen-silent-fail` — hooks fired but returned empty output (≥50% empty rate)

## Iter 2 — trace observability + AST audits

- [x] **#101** `kaizen-turn-density` — events-per-turn rollup over trace JSONL
- [x] **#102** `kaizen-prompt-rhythm` — time between `UserPromptSubmit` events (mean / median / list)
- [x] **#62** `kaizen-hook-cascade` — pairs of hooks that fire within `--window-seconds` of each other
- [x] **#27** `kaizen-heavy-imports` — AST scan for eager (module-level) imports of heavy deps
- [x] **#32** `kaizen-subprocess-rc` — AST scan for `subprocess.run(...)` calls whose rc is dropped
- [x] **#30** `kaizen-hook-trace-coverage` — every `hooks/claude/*.sh` references `_trace.sh`
- [x] **#31** `kaizen-mcp-trace-coverage` — every `*_mcp.py` emits trace events (`_envelope` / `emit_trace`)
- [x] **#16** `kaizen-schema-load-coverage` — every `domain/schemas/*.json` is referenced by some loader
- [x] **#20** `kaizen-density` (was test-density) — public-function vs test-method ratio per script
- [x] **#78** `kaizen-prompt-event-diff` — slice trace events by `UserPromptSubmit` boundaries

## Iter 3 — content + name quality + markdown lint

- [x] **#4** `kaizen-unused-env` — env-vars declared in `.kaizen.toml` but never read from any script
- [x] **#5 + #6** `kaizen-md-link-rot` — relative markdown links that don't resolve on disk (covers both ideas)
- [x] **#11** `kaizen-class-name-quality` — AST scan for non-CamelCase class names
- [x] **#8** `kaizen-md-whitespace` — trailing whitespace + tab-indent scan in `*.md`
- [x] **#7** `kaizen-md-heading-depth` — flag heading-depth jumps (`#` → `###` without `##`)
- [x] **#9** `kaizen-md-dupes` — duplicate-heading detection within one file
- [x] **#2** `kaizen-todo-inventory` — TODO/FIXME/HACK/XXX marker inventory
- [x] **#12** `kaizen-tname-quality` (was test-name-quality) — flag too-short test method names
- [x] **#13** `kaizen-var-name-quality` — flag single-letter module-level variables

## Boy-Scout fix (mid-iter-3)

- [x] **rename** — three scripts originally named `test_*.py` shadowed `unittest discover` via sys.path. Renamed to non-`test_` prefixes (`sandbox_check.py` / `density.py` / `tname_quality.py`), paired tests + bin symlinks + plugin.json perms rewired. Authorized via `KAIZEN_ALLOW_DELETE=1` for the same-session bin-symlink replacements.

## What did NOT ship this run

From the top-pick / tier-1 queue (next-up for a future loop):

- [ ] **#57** vertical-A per-feature lifecycle audit (git+trace)
- [ ] **#92** join-E trace + token-bloat causal weight
- [ ] **#151** substrate-K append-to universal pattern refactor
- [ ] **#153** substrate-K stream join CLI (trace + dxm on session_id)
- [ ] **#161** axis-as-yaml + generic runner (declarative axis loader — would consolidate the 30 shipped here)

Tier-2 still open: #1 comment-quality, #10 function-name quality, #18 validator-wiring, #23 mock-vs-real coverage pairing, #24 mutation-testing kill-ratio (mutmut), #47 iron-law conformance per-feature.

255 deferred ideas remain in the source JSONL.

## Resume

To continue:

```bash
/kaizen:tdd run another 10 from the same priority queue
```

Or re-score the source JSONL through the BK-012 `kaizen-brainstorm` (now shipped) to get rubric-classified picks:

```bash
kaizen-brainstorm score \
    --input ~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl \
    --rubric plugins/kaizen/skills/brainstorming/domain/brainstorm-rubric.yaml \
    --json
```
