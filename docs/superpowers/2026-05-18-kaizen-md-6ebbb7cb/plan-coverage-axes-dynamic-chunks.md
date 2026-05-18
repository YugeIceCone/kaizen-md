# Coverage-axes — dynamic chunk decomposition (15 chunks + MERGE)

- **Date:** 2026-05-18
- **Scope:** drain ALL remaining tier-1/2/3 brainstorm ideas (23 newly enumerated + 3 new from prior chunk-4) + axis-runner (#161) + cross-repo wiring = **27 deliverables across 15 chunks**, fully parallel-safe.
- **Projects:** `~/workspace/kaizen-md`, `~/workspace/semantic-search`
- **Source:** `~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl` (300 ideas)
- **Coverage after this plan:** tier-1 (21/21 ✓), tier-2 (12/12 ✓), tier-3 (17/17 ✓) — **all priority tiers complete**. Tier-4 (250) deferred.
- **Template followed:** `docs/superpowers/templates/chunk-plan-template.md`
- **Sibling docs:** `2026-05-18-coverage-axes-5-chunks.md` (the prior 5-chunk shape, kept for shape reference)

## Token-cost model (per subagent chunk)

| Component         | Range       | Notes                                                     |
|-------------------|-------------|-----------------------------------------------------------|
| Setup             | 12-18k      | system prompt + 2 skill loads + 1-2 exemplar reads        |
| Per axis          | 6-10k       | test write + RED + script + bin + perm + GREEN + commit   |
| Close-out         | 2-3k        | full suite output + fragment writes + close commit        |
| Retry buffer      | +15%        | for typos / gate warns / brief re-RED loops               |

**Density target: 2 substantive axes per chunk ≈ 28-39k tokens (within 20-40k cap).**
- 1 axis ≈ 24-30k (minimum-density, for design-heavy items like axis-runner subparts)
- 2 axes ≈ 32-39k (typical — chosen for 11 of 15 chunks)
- 3 grep/regex axes ≈ 32-40k (only when all 3 are trivial)
- Cross-repo / MERGE ≈ 20-26k (different repo / parent-driven, less setup)

## Orchestration

| # | Title                                          | Items (#IDs)           | Deps | Concur with | Subagent           | Project        | Worktree              | Budget |
|---|------------------------------------------------|------------------------|------|-------------|--------------------|----------------|-----------------------|--------|
| 1 | Foundation AST — naming + iron-law             | #10, #47               | —    | 2-15        | kaizen-implementer | kaizen-md      | `chunk-1-ast-naming`  | ~32k   |
| 2 | Foundation AST — wiring + mocking              | #18, #23               | —    | 1, 3-15     | kaizen-implementer | kaizen-md      | `chunk-2-ast-wiring`  | ~32k   |
| 3 | Foundation AST — comments + domain-yaml        | #1, #19                | —    | 1-2, 4-15   | kaizen-implementer | kaizen-md      | `chunk-3-ast-content` | ~32k   |
| 4 | Trace — lifecycle + bloat join                 | #57, #92               | —    | 1-3, 5-15   | kaizen-implementer | kaizen-md      | `chunk-4-trace-join`  | ~32k   |
| 5 | Trace — stream-join + append-to refactor scan  | #153, #151             | —    | 1-4, 6-15   | kaizen-implementer | kaizen-md      | `chunk-5-trace-merge` | ~32k   |
| 6 | Perf — latency budget + cold-start             | #26, #28, #29          | —    | 1-5, 7-15   | kaizen-implementer | kaizen-md      | `chunk-6-perf`        | ~38k   |
| 7 | Axis runner — design + core                    | (#161 part 1)          | —    | 1-6, 8-15   | kaizen-implementer | kaizen-md      | `chunk-7-runner-core` | ~35k   |
| 8 | Axis runner — MCP + reference YAML             | (#161 part 2)          | —    | 1-7, 9-15   | kaizen-implementer | kaizen-md      | `chunk-8-runner-mcp`  | ~30k   |
| 9 | Test quality — mutation + skipped              | #24, #21               | —    | 1-8, 10-15  | kaizen-implementer | kaizen-md      | `chunk-9-mutation`    | ~32k   |
| 10| Test quality — assertion + parametrize         | NEW, NEW               | —    | 1-9, 11-15  | kaizen-implementer | kaizen-md      | `chunk-10-tests`      | ~32k   |
| 11| Test quality — error-path + dxm-registry       | NEW, #33               | —    | 1-10, 12-15 | kaizen-implementer | kaizen-md      | `chunk-11-tests-obs`  | ~32k   |
| 12| Docs lint — skill-md sections + refs           | #39, #40               | —    | 1-11, 13-15 | kaizen-implementer | kaizen-md      | `chunk-12-docs-skill` | ~30k   |
| 13| Docs lint — slash docstring + CHANGELOG        | #41, #42               | —    | 1-12, 14-15 | kaizen-implementer | kaizen-md      | `chunk-13-docs-cli`   | ~30k   |
| 14| Convention — CC drift + arch-log alignment     | #48, #49               | —    | 1-13, 15    | kaizen-implementer | kaizen-md      | `chunk-14-convention` | ~30k   |
| 15| Cross-repo audit — semantic-search             | (no IDs — wiring)      | —    | 1-14        | general-purpose    | semantic-search| n/a (different repo)  | ~24k   |
| M | MERGE — consolidate + retrofit + x-pollinate   | (fragments + retrofit) | 1-15 | —           | parent orchestrator| kaizen-md + ss | master                | ~22k   |

**Total budget: ~475k tokens across 15 parallel chunks + MERGE.**

**Coverage delivered:**
- Tier 1: 5 newly enumerated (16 already shipped) = 21/21 ✓
- Tier 2: 5 newly enumerated (7 already shipped)  = 12/12 ✓
- Tier 3: 13 newly enumerated (4 already shipped) = 17/17 ✓
- 3 NEW (chunks 10-11 — assertion/parametrize/error-path)
- Axis runner (#161) + MCP wrapper
- Cross-repo audit (semantic-search side)
- Tier 4 (250 ideas) intentionally deferred

**Dispatch — single message, 15 parallel Agent calls:**

```python
[
    Agent(chunk-1), Agent(chunk-2), Agent(chunk-3), Agent(chunk-4), Agent(chunk-5),
    Agent(chunk-6), Agent(chunk-7), Agent(chunk-8), Agent(chunk-9), Agent(chunk-10),
    Agent(chunk-11), Agent(chunk-12), Agent(chunk-13), Agent(chunk-14), Agent(chunk-15),
]
# After all 15 complete → parent runs the MERGE step from this plan's footer.
```

The orchestrator (parent) can also dispatch in waves of 5 if subagent slots are constrained — chunks are dep-free so any partition is safe.

---

## Per-chunk specs

> Each chunk follows the template's 4-section shape: **Guide / Task list (checklist) / Plan / TDD code chunks** + footers **Done when** and **Dispatch**. The full TDD code chunks section is intentionally compact here — the canonical exemplar shape is in `2026-05-18-coverage-axes-5-chunks.md::chunk-1::TDD code chunks` and the template at `docs/superpowers/templates/chunk-plan-template.md`. Refer to them for the per-item RED/GREEN/commit shape; only the chunk-specific assertions and impl outlines are inlined below.

### Chunk 1 — Foundation AST: naming + iron-law

| field        | value                                                                       |
|--------------|-----------------------------------------------------------------------------|
| **Purpose**  | 2 small AST audits — fn-name verb-match + iron-law-per-feature rollup       |
| **Project**  | kaizen-md                                                                   |
| **Deps**     | —                                                                           |
| **Outputs**  | `{fn_name_quality,iron_law_per_feature}.py` + tests + bins                  |
| **Subagent** | kaizen-implementer                                                          |
| **Isolation**| worktree `chunk-1-ast-naming`                                               |
| **Budget**   | ~32k tokens (~50-60 tool calls)                                             |

**Guide:** Working dir `/home/cherry86/workspace/kaizen-md`. Skills: `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`. Exemplar: `skills/workflow/scripts/class_name_quality.py`. Convention: `_envelope.emitter`, `scan_text(source, *, path)` pure-fn, `report`/`gaps` subcommands. NEVER name scripts `test_*.py`.

**Task list (checklist):**
- [ ] **C1.A** `kaizen-fn-name-quality` (#10) — AST: function names start with verb
- [ ] **C1.B** `kaizen-iron-law-per-feature` (#47) — rollup iron-laws JSON by feature dir
- [ ] **C1.C** chunk close-out — full suite + `.chunks/1/{perms.json,progress.md}` fragments

**Plan:** create `{fn_name_quality,iron_law_per_feature}.py` + paired tests + bin symlinks + fragment writes to `.chunks/1/`.

**Isolation contract:**
- **Owns:** `skills/workflow/scripts/{fn_name_quality,iron_law_per_feature}.py`, `tests/test_{fn_name_quality,iron_law_per_feature}.py`, `bin/kaizen-{fn-name-quality,iron-law-per-feature}`, `.chunks/1/`
- **NEVER writes:** `plugin.json`, `progress.md`, `backlog.json`, `gateway.py::SUBSERVERS`, any other chunk's owned paths

**TDD code chunks** — see `2026-05-18-coverage-axes-5-chunks.md::chunk-1::items C1.A, C1.D` for the full RED/GREEN/commit shape. Both items have well-known AST patterns:
- C1.A: `ast.FunctionDef` walk + verb-prefix list (`get/set/build/parse/load/save/run/scan/find/...`)
- C1.B: shell out to `kaizen-iron-laws check --json`, group findings by `path.split("/")[2]`

**Done when:** 2 axes green + paired tests + bins + `.chunks/1/{perms.json, progress.md}` present; 0 regressions.

**Dispatch:**
```python
Agent(description="Coverage chunk 1 — naming + iron-law",
      subagent_type="kaizen-implementer", isolation="worktree",
      prompt="""Implement chunk 1 of docs/superpowers/plans/2026-05-18-coverage-axes-dynamic-chunks.md.
WORKING DIR: /home/cherry86/workspace/kaizen-md
READ FIRST: chunk-1 above + class_name_quality.py exemplar + chunk-plan-template.md::isolation-contract
SKILLS: kaizen:tdd, kaizen:plugin-development
EXECUTE: C1.A → C1.C, RED→GREEN→commit per item.
NEVER write: plugin.json, progress.md, backlog.json, gateway.py. Fragments only.
BUDGET: ~32k. DONE WHEN: 2 axes green, 0 regressions, .chunks/1/ fragments present.""")
```

---

### Chunk 2 — Foundation AST: wiring + mocking

| Header                                                                                                    |
|-----------------------------------------------------------------------------------------------------------|
| Items #18 `validator-wiring` (`json.load` w/o `.validate`) + #23 `mock-real-pairing` (`mock.patch` w/o `_live` sibling) |
| Project: kaizen-md · Deps: — · Worktree: `chunk-2-ast-wiring` · Budget: ~32k                              |

**Guide / Plan / Isolation contract:** same shape as chunk 1 (exclusive owns of just-its-files), fragments at `.chunks/2/`. Exemplars: `subprocess_rc.py` (AST Visitor pattern), `heavy_imports.py` (top-level filter).

**Task list:**
- [ ] **C2.A** `kaizen-validator-wiring` (#18) — AST visit `json.load` calls, flag if no `.validate` in same scope
- [ ] **C2.B** `kaizen-mock-real-pairing` (#23) — AST visit `mock.patch(...)` string args, flag without `_live.py` sibling
- [ ] **C2.C** chunk close-out

**Dispatch:** identical prompt shape to chunk 1, swap items + worktree name.

---

### Chunk 3 — Foundation AST: comments + domain-yaml

| Header                                                                                                          |
|-----------------------------------------------------------------------------------------------------------------|
| Items #1 `comment-quality` (rewrite-without-loss) + #19 `domain-yaml-strict` (PyYAML strict-mode lint over `domain/*.yaml`) |
| Project: kaizen-md · Deps: — · Worktree: `chunk-3-ast-content` · Budget: ~32k                                   |

**Task list:**
- [ ] **C3.A** `kaizen-comment-quality` (#1) — comment tokens ⊆ next code line tokens (Jaccard ≥0.8 → flag)
- [ ] **C3.B** `kaizen-yaml-strict` (#19) — load all `**/domain/**/*.yaml` with `yaml.safe_load`; flag parse errors / duplicate keys / unknown ops
- [ ] **C3.C** chunk close-out → `.chunks/3/`

---

### Chunk 4 — Trace: lifecycle + bloat join

| Items #57 `lifecycle-audit` + #92 `trace-bloat-join` · Worktree: `chunk-4-trace-join` · Budget: ~32k |

**Guide:** Exemplars: `turn_density.py`, `silent_fail.py`. Conventions: trace log at `~/.claude/.kaizen/trace/events.jsonl`; graceful `trace_log not found` path. Token-bloat data at `~/.claude/.kaizen/token-bloat/*.jsonl`.

**Task list:**
- [ ] **C4.A** `kaizen-lifecycle-audit` (#57) — merge `git log --grep=<feature>` + trace events matching feature, sorted by ts
- [ ] **C4.B** `kaizen-trace-bloat-join` (#92) — inner-join trace + token-bloat on `session_id`
- [ ] **C4.C** chunk close-out → `.chunks/4/`

---

### Chunk 5 — Trace: stream-join + append-to scan

| Items #153 `stream-join` + #151 `append-to-audit` · Worktree: `chunk-5-trace-merge` · Budget: ~32k |

**Task list:**
- [ ] **C5.A** `kaizen-stream-join` (#153) — heapq-merge trace + dxm streams, filterable by `--session SID`
- [ ] **C5.B** `kaizen-append-to-audit` (#151) — AST visit `open(..., "a")` calls; flag if file lacks `_atomic` import (suggest `atomic_append_line`)
- [ ] **C5.C** chunk close-out → `.chunks/5/`

---

### Chunk 6 — Perf: latency budget + cold-start (3 items)

| Items #26 `mcp-latency-budget` + #28 `cold-start-time` + #29 `cold-start-cost-map` · Worktree: `chunk-6-perf` · Budget: ~38k |

**Guide:** trace JSONL has per-tool ts + duration_ms (where attached) per CLAUDE.md. Cold-start = time from process start to first stdout per tool.

**Task list:**
- [ ] **C6.A** `kaizen-mcp-latency` (#26) — per-tool p50/p95 from trace ts deltas; flag p95 > threshold
- [ ] **C6.B** `kaizen-cold-start` (#28) — measure each MCP/script first-stdout time via `time` subprocess
- [ ] **C6.C** `kaizen-cold-start-map` (#29) — aggregate C6.B's output into a sorted cost map (CSV / envelope)
- [ ] **C6.D** chunk close-out → `.chunks/6/`

Note: 3 items because they share the same trace/timing substrate — measurement happens once, the 3 axes are different views.

---

### Chunk 7 — Axis runner: design + core (axis_runner part 1)

| Build `axis.schema.json` + `axis_runner.py` + `axis_runner_rules.py` · Worktree: `chunk-7-runner-core` · Budget: ~35k |

**Guide:** Skills: `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`, `Skill(kaizen:decision-rubric)`. Exemplar: `schema_cli.py::BucketWalker`. DESIGN GATE: write `axis.schema.json` FIRST and self-review against 3-4 already-shipped axes for fit before any runner code.

**Task list:**
- [ ] **C7.A** Design + write `axis.schema.json` (3 scan-spec types: `grep` / `ast-rule` / `file-coverage`)
- [ ] **C7.B** `axis_runner.py` — YAML loader + dispatch by `scan_spec.type`; envelope-shaped output
- [ ] **C7.C** `axis_runner_rules.py` — rule lib: `run_grep`, `run_ast_rule`, `run_file_coverage`
- [ ] **C7.D** chunk close-out → `.chunks/7/`

NO retrofit in chunk 7 (deferred to MERGE).

---

### Chunk 8 — Axis runner: MCP + reference YAML (axis_runner part 2)

| Build `axis_runner_mcp.py` + 1 reference YAML axis + paired tests · Worktree: `chunk-8-runner-mcp` · Budget: ~30k |

**Task list:**
- [ ] **C8.A** `axis_runner_mcp.py` — FastMCP wrapper; tools: `list_axes`, `run_axis`, `report`
- [ ] **C8.B** `reference_demo.yaml` — proof-of-subsumption YAML axis using `grep` dispatcher
- [ ] **C8.C** `test_axis_runner_e2e.py` — load reference_demo.yaml → run → verify envelope shape
- [ ] **C8.D** chunk close-out → `.chunks/8/{perms.json, progress.md, mcp-mounts.txt}` (mcp-mounts ← `("axis_runner", "axis_runner_mcp")`)

NOTE: chunk 8 can start in parallel with chunk 7 IF it stubs the runner import. Simpler to dispatch chunk 8 in the same wave as 7 — they touch different files (axis_runner.py vs axis_runner_mcp.py). Validation that they integrate happens in MERGE.

---

### Chunk 9 — Test quality: mutation + skipped

| Items #24 `mutation-gate` + #21 `skipped-test-ratio` · Worktree: `chunk-9-mutation` · Budget: ~32k |

**Guide:** Exemplar: `dead_code.py` (graceful-skip-when-dep-missing).

**Task list:**
- [ ] **C9.A** `kaizen-mutation-gate` (#24) — mutmut wrapper, graceful-skip, kill-ratio target ≥0.8; opt-in via `KAIZEN_MUTATION_TEST_LIVE=1`
- [ ] **C9.B** `kaizen-skipped-test-ratio` (#21) — count `@unittest.skip*` + `self.skipTest(...)` per test file; flag files where ratio >0.5
- [ ] **C9.C** chunk close-out → `.chunks/9/`

---

### Chunk 10 — Test quality: assertion + parametrize (NEW axes)

| NEW: assertion-density + parametrize-coverage · Worktree: `chunk-10-tests` · Budget: ~32k |

**Task list:**
- [ ] **C10.A** `kaizen-assertion-density` — AST: `test_*` methods with body but no `self.assert*` call
- [ ] **C10.B** `kaizen-parametrize-coverage` — AST: detect 3+ near-identical `test_*` methods (Levenshtein ≤20 on body); suggest `@parametrize`
- [ ] **C10.C** chunk close-out → `.chunks/10/`

---

### Chunk 11 — Test quality: error-path + dxm registry

| Items NEW error-path-coverage + #33 dxm-event-type-registry · Worktree: `chunk-11-tests-obs` · Budget: ~32k |

**Task list:**
- [ ] **C11.A** `kaizen-error-path` — AST scan scripts for `raise X` statements; cross-reference with test files for `assertRaises(X)`; flag uncovered exception classes
- [ ] **C11.B** `kaizen-dxm-event-registry` (#33) — scan all `*.sh` and `*_mcp.py` for `dxm-event` invocations + their event types; build a unified registry; flag uses of unregistered types
- [ ] **C11.C** chunk close-out → `.chunks/11/`

---

### Chunk 12 — Docs lint: skill-md sections + refs

| Items #39 `skill-md-sections-audit` + #40 `skill-md-refs-coverage` · Worktree: `chunk-12-docs-skill` · Budget: ~30k |

**Task list:**
- [ ] **C12.A** `kaizen-skill-sections` (#39) — every `SKILL.md` must contain a known set of section headers (define in `domain/skill-required-sections.yaml`); flag missing
- [ ] **C12.B** `kaizen-skill-refs` (#40) — every `references/<x>.md` must be linked from at least one SKILL.md
- [ ] **C12.C** chunk close-out → `.chunks/12/`

---

### Chunk 13 — Docs lint: slash docstring + CHANGELOG

| Items #41 `slash-cmd-docstring` + #42 `changelog-entry-per-tag` · Worktree: `chunk-13-docs-cli` · Budget: ~30k |

**Task list:**
- [ ] **C13.A** `kaizen-slash-docstring` (#41) — every `commands/*.md` must have non-empty description + ≥1 paragraph body
- [ ] **C13.B** `kaizen-changelog-tag-coverage` (#42) — every git tag (or every release commit) has a matching `CHANGELOG.md` entry
- [ ] **C13.C** chunk close-out → `.chunks/13/`

---

### Chunk 14 — Convention: CC drift + arch-log alignment

| Items #48 `cc-drift` + #49 `arch-log-row-alignment` · Worktree: `chunk-14-convention` · Budget: ~30k |

**Task list:**
- [ ] **C14.A** `kaizen-cc-drift` (#48) — diff `git log --pretty=%s` against `CHANGELOG.md` headings; flag commits without matching CHANGELOG row (within last N commits)
- [ ] **C14.B** `kaizen-archlog-alignment` (#49) — every structural-change commit (per kaizen gate's classification) MUST have a matching row appended to `progress.md` in the same commit
- [ ] **C14.C** chunk close-out → `.chunks/14/`

---

### Chunk 15 — Cross-repo: semantic-search wiring

| Run the 30 pre-existing axes against semantic-search; wire 3 gates · Project: semantic-search · Budget: ~24k |

**Guide:** Different repo — entirely isolated. NO fragment dir (semantic-search merges happen in-place). Use `kaizen backlog add` CLI (not raw JSON edits) for backlog mutations.

**Task list:**
- [ ] **C15.A** Verify `command -v kaizen-perm-coverage` exits 0 from semantic-search cwd
- [ ] **C15.B** Run the 30 pre-existing axes; write `~/workspace/semantic-search/docs/2026-MM-DD-coverage-findings.md`
- [ ] **C15.C** File top-10 findings via `kaizen backlog add --section next_up --ref kaizen-md-axis-name`
- [ ] **C15.D** Wire 3 axes (perm-coverage + bin-coverage + heavy-imports) into semantic-search `verify_cmd`
- [ ] **C15.E** close-out commit refs this plan path

NO write to kaizen-md. NO write to chunks 1-14's outputs (cross-pollination happens in MERGE).

---

## MERGE step (parent orchestrator only — never chunk agents)

Same shape as `2026-05-18-coverage-axes-5-chunks.md::Merge step`, scaled to 14 fragment dirs (chunk 15 produces no fragment).

**Trigger:** all 14 chunk-branches merged to kaizen-md master + chunk 15 committed in semantic-search.

**Actions (sequential, single-writer):**

1. **Perm consolidation** — read `.chunks/{1..14}/perms.json`, dedupe-append to `plugin.json::permissions.allow`.
2. **Architecture log** — concat `.chunks/{1..14}/progress.md` to `.kaizen/workflow/progress.md` in chunk order.
3. **Backlog** — for each `.chunks/{1..14}/backlog.jsonl`, dispatch `kaizen backlog add` per row.
4. **MCP mount** — read `.chunks/8/mcp-mounts.txt` (`("axis_runner", "axis_runner_mcp")`), edit `gateway.py::SUBSERVERS` to append.
5. **Retrofit (the deferred work)** — now that `axis_runner` (chunks 7+8) AND all standalone axes (chunks 1-6, 9-14) coexist, retrofit ≥10 simple grep/regex axes to YAML form:
   - Write `domain/axes/<name>.yaml` per retrofitted axis
   - Re-target `bin/kaizen-<name>` to `axis_runner.py`
   - Update paired tests to call `axis_runner.run_axis(yaml_path)`
   - Delete legacy `.py` (use `KAIZEN_ALLOW_DELETE=1`)
   - Remaining un-retrofitted axes stay parked as BK-NNN
6. **Cross-pollination** — run chunks 1-14's new axes against semantic-search; append findings to `~/workspace/semantic-search/docs/...findings.md`; file high-signal findings as backlog items.
7. **Cleanup** — `rm -rf .chunks/`.
8. **Single merge commit** — `chore(merge): consolidate chunks 1-15 + retrofit + cross-pollination (Refs: docs/.../dynamic-chunks.md)`.
9. **Final verification** — full suite + `test-pipeline.sh`; 0 regressions.

**MERGE budget: ~22k tokens** (parent, mostly file ops + sequential edits, minimal new design).

---

## Plan-level done when

- [ ] All 15 chunks' per-chunk "Done when" gates clear
- [ ] All 14 kaizen-md chunk branches merged to master + chunk 15 committed in semantic-search
- [ ] MERGE step's 9 actions completed
- [ ] `.chunks/` directory deleted
- [ ] Master checklist (`2026-05-18-coverage-checklist.md`) flips 23 newly-shipped rows + 3 NEW + axis-runner + ≥10 retrofits = ~37 rows to `[x]`
- [ ] Coverage rollup: tier-1 (21/21), tier-2 (12/12), tier-3 (17/17), all priority tiers complete
- [ ] Final smoke: `bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh` green

## How to dispatch (operator runbook)

**Option A — full parallel (15 agents at once):**
```python
# Single message — 15 Agent() calls. Each gets a fresh subagent context.
[Agent(c) for c in chunks_1_through_15]
```
Peak token budget ≈ 475k across all 15 (avg ~32k per chunk × 15).

**Option B — waves of 5 (if slot-limited):**
```python
# Wave 1
[Agent(c) for c in chunks_1_through_5]
# Wait for completion, then Wave 2
[Agent(c) for c in chunks_6_through_10]
# Wave 3
[Agent(c) for c in chunks_11_through_15]
```
Same total budget, just sequentialized.

**Option C — sequential (one at a time):**
- Slowest but safest if any chunk fails — easy to diagnose.

**All three options are safe** because chunks are dep-free. The MERGE step always runs LAST regardless of wave shape.
