# Coverage-axes next-50 — 5-chunk plan

- **Date:** 2026-05-18
- **Scope:** drain the remaining tier-1/2 coverage-axes queue (10 items) + select tier-3 wins (~25), land the generic axis runner (#161) that retrofits the 30 already-shipped axes, then wire the kaizen-* surface into the semantic-search consumer.
- **Projects:** `~/workspace/kaizen-md`, `~/workspace/semantic-search`
- **Source / brainstorm:** `~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl` (lines 1-300)
- **Sibling docs:** `2026-05-18-coverage-checklist.md` (300-row master), `2026-05-18-coverage-loop-implemented.md` (this-run narrative)
- **Total chunks:** 5
- **Concurrency:** phase-1 chunks 1+2 parallel; phase-2 chunk 3 sequential (after 1+2); phase-3 chunks 4+5 parallel (after 3)
- **Verification cadence:** per-item paired tests + per-chunk full suite + plan-level smoke at the end
- **Template followed:** `docs/superpowers/templates/chunk-plan-template.md`

## Orchestration

| Chunk | Title                                         | Deps    | Concurrent with | Subagent           | Project              | Budget   |
|-------|-----------------------------------------------|---------|-----------------|--------------------|----------------------|----------|
| 1     | Foundation AST audits                         | —       | 2               | kaizen-implementer | kaizen-md            | ~80 calls |
| 2     | Trace-observability deep-dive                 | —       | 1               | kaizen-implementer | kaizen-md            | ~80 calls |
| 3     | Generic axis runner (#161) + retrofit         | 1, 2    | —               | kaizen-implementer | kaizen-md            | ~120 calls|
| 4     | Test quality + mutation gating                | 3       | 5               | kaizen-implementer | kaizen-md            | ~70 calls |
| 5     | Cross-project wiring into semantic-search     | 3       | 4               | general-purpose    | semantic-search      | ~50 calls |

The orchestrator (parent / human) dispatches phase by phase:

```python
# Phase 1 — parallel
[Agent(chunk-1), Agent(chunk-2)]   # same message, run in parallel

# Phase 2 — sequential (waits for 1+2)
Agent(chunk-3)

# Phase 3 — parallel (after 3)
[Agent(chunk-4), Agent(chunk-5)]
```

Total: 35-40 net-new axes + 1 meta-runner + cross-project wiring across ~3 sessions of subagent work.

---

## Chunk 1: Foundation AST audits

| field        | value                                                                          |
|--------------|--------------------------------------------------------------------------------|
| **Purpose**  | 5 small AST-based code-quality audits, all stdlib-only, all paired-test shape  |
| **Project**  | `~/workspace/kaizen-md`                                                        |
| **Deps**     | —                                                                              |
| **Outputs**  | `skills/workflow/scripts/{fn_name_quality,validator_wiring,mock_real_pairing,iron_law_per_feature,comment_quality}.py` + paired tests + bin + perm |
| **Subagent** | `kaizen-implementer`                                                           |
| **Isolation**| `worktree`                                                                     |
| **Budget**   | ~80 tool calls (5 items × ~16 calls each)                                      |

### Context block

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills to load:** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`
- **Template axes (read first):** `plugins/kaizen/skills/workflow/scripts/{class_name_quality,heavy_imports,subprocess_rc}.py` — same shape; copy + adapt.
- **Conventions:**
  - `_envelope.emitter("kaizen-<n>", tool_version="1.0.0")` for output
  - `report` / `gaps` subcommands; `gaps` exit code 1 when violations > 0
  - Pure-fn `scan_text(source, *, path) -> list[dict]` for AST scans
  - Never name scripts `test_*.py` (Boy-Scout learning from this-run rename)
- **Decisions upstream:** the 30 axes from `2026-05-18-coverage-loop-implemented.md` are all in master; build on top, don't re-do.

### Task list

```yaml
- subject: "C1.A — kaizen-fn-name-quality (#10)"
  description: "AST: function names start with verb (compare to body verbs)"
- subject: "C1.B — kaizen-validator-wiring (#18)"
  description: "AST: schema loaders that load JSON but never call .validate"
- subject: "C1.C — kaizen-mock-real-pairing (#23)"
  description: "tests that mock X but no live-integration test exists for X"
- subject: "C1.D — kaizen-iron-law-per-feature (#47)"
  description: "rollup iron-law findings grouped by owning feature/skill"
- subject: "C1.E — kaizen-comment-quality (#1)"
  description: "rewrite-without-loss heuristic — comments that just restate code"
- subject: "C1.F — chunk close-out"
  description: "full suite + arch log + commit refs chunk-1"
```

### Plan (file inventory)

| Action  | Path                                                                   | Responsibility                                |
|---------|------------------------------------------------------------------------|-----------------------------------------------|
| Create  | `plugins/kaizen/skills/workflow/scripts/fn_name_quality.py`            | AST verb-vs-name match                        |
| Create  | `plugins/kaizen/skills/workflow/scripts/validator_wiring.py`           | AST: json.load + no .validate call            |
| Create  | `plugins/kaizen/skills/workflow/scripts/mock_real_pairing.py`          | AST: scan test files for `mock.patch` w/ no `_live.py` sibling |
| Create  | `plugins/kaizen/skills/workflow/scripts/iron_law_per_feature.py`       | parse iron-laws JSON output, group by feature |
| Create  | `plugins/kaizen/skills/workflow/scripts/comment_quality.py`            | comment-vs-code redundancy heuristic          |
| Create  | `plugins/kaizen/tests/test_<each>.py`                                  | paired test per script                        |
| Create  | `plugins/kaizen/bin/kaizen-<each>`                                     | bin symlink per script                        |
| Modify  | `plugins/kaizen/.claude-plugin/plugin.json`                            | 5 × `Bash(python3 ...:*)` + 5 × `Bash(bin/...)` perms |

### TDD code units

#### item C1.A — kaizen-fn-name-quality (#10)

**RED** (`tests/test_fn_name_quality.py`):
```python
def test_get_user_starts_with_verb(self):
    findings = fn_name_quality.scan_text("def get_user(): pass\n", path="ok.py")
    self.assertEqual(findings, [])

def test_user_data_missing_verb(self):
    findings = fn_name_quality.scan_text("def user_data(): pass\n", path="bad.py")
    self.assertEqual(findings[0]["rule"], "no-leading-verb")
```

**GREEN outline:** AST walk top-level FunctionDefs; first underscore-segment must match a known-verb prefix list (`get/set/build/parse/load/save/run/scan/find/...`).

**Commit:** `feat(fn-name-quality): AST verb-vs-name check (chunk 1 item A)`

#### item C1.B — kaizen-validator-wiring (#18)

**RED** (`tests/test_validator_wiring.py`):
```python
def test_load_without_validate_flagged(self):
    src = 'import json\nwith open("x.json") as f: schema = json.load(f)\n'
    findings = validator_wiring.scan_text(src, path="bad.py")
    self.assertTrue(any(f["rule"] == "loads-but-no-validate" for f in findings))

def test_load_with_validate_ok(self):
    src = 'import json\nfrom jsonschema import validate\n' \
          'schema = json.load(open("x.json"))\nvalidate(data, schema)\n'
    findings = validator_wiring.scan_text(src, path="ok.py")
    self.assertEqual(findings, [])
```

**GREEN outline:** AST visit `json.load(...)` calls; check whether the same module also calls a function named `validate` (jsonschema convention) or has a `.validate()` method call.

**Commit:** `feat(validator-wiring): AST scan for orphan schema loads (chunk 1 item B)`

#### item C1.C — kaizen-mock-real-pairing (#23)

**RED:** test file references `mock.patch("foo.bar")` → expects sibling `_live.py` or `--live` opt-in test for `foo.bar`.

**GREEN outline:** AST visit `mock.patch(...)` string args, collect mocked targets; cross-reference with `*_live.py` test files in same dir.

**Commit:** `feat(mock-real-pairing): flag mocked targets w/o live counterpart (chunk 1 item C)`

#### item C1.D — kaizen-iron-law-per-feature (#47)

**RED:** given a stub `iron_laws.json` with 3 findings → rollup returns dict grouped by feature dir.

**GREEN outline:** shell out to `kaizen-iron-laws check --json`, parse output, key by `path.split("/")[2]` (the feature dir), emit grouped envelope.

**Commit:** `feat(iron-law-per-feature): rollup iron-law findings by feature (chunk 1 item D)`

#### item C1.E — kaizen-comment-quality (#1)

**RED:** a comment `# increment counter\ncounter += 1` flagged; `# guard against legacy 0.x state\nif legacy_state(): ...` not flagged.

**GREEN outline:** AST + adjacent-line check: comment is "redundant" if all its tokens appear in the next code line (lemmatize loosely — verbs map to identifier verbs).

**Commit:** `feat(comment-quality): rewrite-without-loss heuristic (chunk 1 item E)`

#### item C1.F — chunk close-out

- Run full suite: `cd plugins/kaizen && python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
- Append architecture log row summarizing 5 axes + test-baseline delta.
- Commit message: `chore(progress): chunk 1 close-out — 5 foundation AST axes (Refs: docs/.../chunk-1)`

### Done when

- [ ] 5 axes ship green + bin + perm + paired test
- [ ] `python3 -m unittest discover` — 0 regressions on the prior 3153
- [ ] Architecture log row appended
- [ ] Each commit names `chunk 1 item X`

### Dispatch

```python
Agent(
    description="Coverage-axes chunk 1 — Foundation AST audits",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 1 of docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md.

WORKING DIR: /home/cherry86/workspace/kaizen-md

READ FIRST (in order):
1. docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-1
2. docs/superpowers/templates/chunk-plan-template.md (the template the plan follows)
3. plugins/kaizen/skills/workflow/scripts/class_name_quality.py (canonical template axis)

SKILLS TO LOAD: kaizen:tdd, kaizen:plugin-development

EXECUTE: items C1.A → C1.F in order, RED→GREEN→commit per item. Never name a script `test_*.py` — collides with unittest discovery.

DONE WHEN: 5 axes green, 0 regressions on full suite, arch log row appended.

BUDGET: ~80 tool calls. If exhausted, commit green items + write chunk-1-resume.md naming what's left."""
)
```

---

## Chunk 2: Trace-observability deep dive

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | per-feature lifecycle audit + cross-index joins (trace + token-bloat) + the substrate refactor       |
| **Project**  | `~/workspace/kaizen-md`                                                                              |
| **Deps**     | —                                                                                                    |
| **Outputs**  | `lifecycle_audit.py`, `trace_bloat_join.py`, `stream_join.py`, `append_to_universal.py`              |
| **Subagent** | `kaizen-implementer`                                                                                 |
| **Isolation**| `worktree`                                                                                           |
| **Budget**   | ~80 tool calls                                                                                       |

### Context block

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills:** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`
- **Template axes:** `plugins/kaizen/skills/workflow/scripts/{turn_density,prompt_event_diff,silent_fail}.py` — same trace-JSONL-read shape.
- **Trace log location:** `~/.claude/.kaizen/trace/events.jsonl` (per CLAUDE.md `_paths.py`)
- **Token-bloat log:** check `_paths.sh::KAIZEN_TOKEN_BLOAT_*`
- **Conventions:** trace events are JSONL, one per line; fields vary by event type. Always have a `trace_log not found` graceful path.

### Task list

```yaml
- subject: "C2.A — kaizen-lifecycle-audit (#57)"
  description: "git log + trace events for a feature name — surface its history"
- subject: "C2.B — kaizen-trace-bloat-join (#92)"
  description: "join trace + token-bloat on session_id, compute per-feature token weight"
- subject: "C2.C — kaizen-stream-join (#153)"
  description: "CLI: stream-join trace + dxm on session_id, emit unified timeline"
- subject: "C2.D — refactor append-to universal pattern (#151)"
  description: "AST scan for emitters using ad-hoc append; flag for migration to _atomic.atomic_append_line"
- subject: "C2.E — chunk close-out"
  description: "full suite + arch log + commit refs chunk-2"
```

### TDD code units

(Per-item RED/GREEN block — same shape as chunk 1. Truncated here for brevity; the real chunk file inlines them.)

#### item C2.A — kaizen-lifecycle-audit (#57)

**RED:** given a feature name "brainstorm", return list of `(ts, kind, summary)` tuples merging git log + trace events about that feature.

**GREEN outline:** `git log --grep="brainstorm"` + grep trace JSONL for matching tool calls / file paths; merge sorted by timestamp.

**Commit:** `feat(lifecycle-audit): per-feature git+trace timeline (chunk 2 item A)`

#### item C2.B — kaizen-trace-bloat-join (#92)

**RED:** synthetic trace + bloat JSONLs sharing session_ids → join returns rows with both event count and bloat-tokens.

**GREEN outline:** index both JSONLs by session_id (dict); inner-join; emit rows.

**Commit:** `feat(trace-bloat-join): join on session_id (chunk 2 item B)`

#### items C2.C, C2.D — see template shape above.

#### item C2.E — chunk close-out as in chunk 1.

### Done when

- [ ] 4 axes green + 1 refactor scan
- [ ] 0 regressions
- [ ] Architecture log row

### Dispatch

```python
Agent(
    description="Coverage-axes chunk 2 — Trace observability",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 2 (parallel with chunk 1). Same shape as the template.

WORKING DIR: /home/cherry86/workspace/kaizen-md
READ: docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-2
SKILLS: kaizen:tdd, kaizen:plugin-development
TEMPLATES (read first): turn_density.py, prompt_event_diff.py
BUDGET: ~80 calls."""
)
```

---

## Chunk 3: Generic axis runner (#161) + retrofit

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | Declarative `axis-as-yaml` + generic runner that consumes any YAML-defined axis. Then retrofit the 30 shipped axes (chunk 1+2 included) to declare themselves in YAML, dropping ~50% of the per-axis Python boilerplate. |
| **Project**  | `~/workspace/kaizen-md`                                                                              |
| **Deps**     | Chunks 1, 2 (need all axes existing to know the common shape)                                        |
| **Outputs**  | `axis_runner.py` + `domain/axes/*.yaml` per axis + `axis_runner_mcp.py` (optional)                   |
| **Subagent** | `kaizen-implementer`                                                                                 |
| **Isolation**| `worktree`                                                                                           |
| **Budget**   | ~120 calls (biggest chunk — design + impl + retrofit)                                                |

### Context block

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills:** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`, `Skill(kaizen:decision-rubric)` (the YAML-walker pattern this builds on)
- **Files to read first (the shape this generalizes):**
  - `skills/workflow/scripts/schema_cli.py::BucketWalker` — the YAML-walker exemplar
  - The 30 shipped axes — note their common shape (`scan(scripts_dir=) → dict`, gaps subcommand, envelope emit)
- **Decision upstream:** YAML schema design is the load-bearing decision; treat as a mini-spec before coding.

### Task list

```yaml
- subject: "C3.A — design axis.schema.json"
  description: "JSON Schema for declarative axes. Validates the YAML axis spec format."
- subject: "C3.B — RED test for axis_runner"
  description: "load YAML axis → run → returns canonical envelope shape"
- subject: "C3.C — GREEN axis_runner.py"
  description: "load YAML, dispatch the scan-spec (grep / ast-rule / file-coverage), emit envelope"
- subject: "C3.D — retrofit md_whitespace as axis YAML"
  description: "prove the runner subsumes one existing axis; delete the .py after"
- subject: "C3.E — retrofit md_heading_depth, md_dupes, todo_inventory, unused_env (4 grep-style axes)"
  description: "5 of 30 axes retrofitted as yaml-only"
- subject: "C3.F — bin/kaizen-axis-runner + perm + docs"
  description: "CLI + docs page listing all yaml-declared axes"
- subject: "C3.G — chunk close-out + decision row"
  description: "full suite, arch log, decision: retrofit-rest-later (BK-NNN) or retrofit-all-now"
```

### Done when

- [ ] `axis_runner.py` + 5+ YAML axes ship
- [ ] At least 5 shipped axes retrofitted (proof of subsumption)
- [ ] Architecture log row documents "axis-as-yaml + generic runner — 5 axes converted, 25 pending parked as BK-NNN"
- [ ] 0 regressions

### Dispatch

```python
Agent(
    description="Coverage-axes chunk 3 — Generic axis runner (#161)",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 3 of the 5-chunk plan. Deps 1+2 must be complete (assert via git log on chunk-1 + chunk-2 commit messages).

WORKING DIR: /home/cherry86/workspace/kaizen-md
READ: docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-3
SKILLS: kaizen:tdd, kaizen:plugin-development, kaizen:decision-rubric
EXEMPLAR: skills/workflow/scripts/schema_cli.py::BucketWalker
BUDGET: ~120 calls (biggest chunk — design heavy).
DESIGN GATE: write the axis.schema.json FIRST and pause to self-review before writing any code that depends on it."""
)
```

---

## Chunk 4: Test quality + mutation gating

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | Mutation testing (#24 mutmut) + 4 tier-3 test-quality axes (assertion-density, fixture-coverage, parametrize-coverage, error-path-coverage) |
| **Project**  | `~/workspace/kaizen-md`                                                                              |
| **Deps**     | Chunk 3 (use the new axis_runner for the simpler ones)                                               |
| **Outputs**  | `mutation_gate.py` + 4 axis YAMLs                                                                    |
| **Subagent** | `kaizen-implementer`                                                                                 |
| **Isolation**| `worktree`                                                                                           |
| **Budget**   | ~70 calls                                                                                            |

### Task list

```yaml
- subject: "C4.A — kaizen-mutation-gate (#24)"
  description: "mutmut wrapper, graceful-skip; target kill-ratio >= 80%"
- subject: "C4.B — assertion-density axis (yaml-decl)"
  description: "tests with body but no assertions"
- subject: "C4.C — parametrize-coverage axis (yaml-decl)"
  description: "repeated near-identical test bodies; suggest parametrize"
- subject: "C4.D — error-path-coverage axis (yaml-decl)"
  description: "scripts that raise but no test catches the exception"
- subject: "C4.E — chunk close-out"
```

### Done when

- [ ] 1 graceful-skip wrapper + 3 yaml-declarative axes
- [ ] Full suite 0 regressions
- [ ] Architecture log row

### Dispatch

```python
Agent(
    description="Coverage-axes chunk 4 — Test quality + mutation",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Chunk 4 — parallel with chunk 5. Deps: chunk 3 (axis_runner). Read the plan, follow the template.

WORKING DIR: /home/cherry86/workspace/kaizen-md
READ: docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-4
BUDGET: ~70 calls."""
)
```

---

## Chunk 5: Cross-project wiring into semantic-search

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | Wire the shipped kaizen-* coverage surface into semantic-search's CI / pre-commit gate. Run all 30+ axes against semantic-search; file the top-N findings as semantic-search backlog items. |
| **Project**  | `~/workspace/semantic-search` (consumer) + read-only refs into `~/workspace/kaizen-md`               |
| **Deps**     | Chunk 3 (the generic runner makes axis dispatch easier from another repo)                            |
| **Outputs**  | `~/workspace/semantic-search/.kaizen.toml` updates + per-axis findings dumped to `semantic-search/docs/2026-MM-DD-coverage-findings.md` |
| **Subagent** | `general-purpose` (cross-repo; not pure kaizen-md work)                                              |
| **Isolation**| none (read-only on kaizen-md, mutating on semantic-search)                                           |
| **Budget**   | ~50 calls                                                                                            |

### Context block

- **Working dirs:** primary `~/workspace/semantic-search`; reference `~/workspace/kaizen-md`
- **Skills:** none specific — this is cross-project plumbing
- **Files (semantic-search side):** `.kaizen.toml`, `.kaizen/workflow/backlog.json`, `tests/`
- **Convention:** don't modify semantic-search source files; only add gate config + findings docs.

### Task list

```yaml
- subject: "C5.A — install kaizen plugin into semantic-search project root"
  description: "verify bin/kaizen-* on $PATH from semantic-search cwd"
- subject: "C5.B — run all 30 shipped axes against semantic-search"
  description: "collect findings into a single docs/2026-MM-DD-coverage-findings.md"
- subject: "C5.C — file top-10 actionable findings into semantic-search backlog"
  description: "kaizen backlog add for each, status=next_up, ref the kaizen-md axis name"
- subject: "C5.D — wire 3 axes into semantic-search verify_cmd"
  description: "perm-coverage + bin-coverage + heavy-imports as gate-blockers"
- subject: "C5.E — chunk close-out + cross-repo handoff"
  description: "summary commit in semantic-search, refs kaizen-md plan path"
```

### Done when

- [ ] semantic-search's `.kaizen.toml` references 3 kaizen-* gates
- [ ] `docs/2026-MM-DD-coverage-findings.md` in semantic-search lists per-axis findings
- [ ] Top-10 findings filed as backlog items in semantic-search
- [ ] Final commit refs `kaizen-md::chunk-5` AND the kaizen-md plan path

### Dispatch

```python
Agent(
    description="Coverage-axes chunk 5 — Wire into semantic-search",
    subagent_type="general-purpose",  # cross-project, not pure kaizen-md work
    prompt="""Chunk 5 — parallel with chunk 4. Deps: chunk 3.

WORKING DIRS: primary /home/cherry86/workspace/semantic-search; ref /home/cherry86/workspace/kaizen-md

READ:
1. /home/cherry86/workspace/kaizen-md/docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-5
2. /home/cherry86/workspace/semantic-search/.kaizen.toml (current state)
3. /home/cherry86/workspace/semantic-search/.kaizen/workflow/backlog.json (existing backlog)

DON'T modify semantic-search source files. Only:
- update .kaizen.toml
- write the findings doc
- file backlog items via `kaizen backlog add`

BUDGET: ~50 calls."""
)
```

---

## Plan-level done when

- [ ] All 5 chunks completed (their per-chunk "Done when" gates clear)
- [ ] Final smoke: `bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh` green
- [ ] Master checklist updated: `2026-05-18-coverage-checklist.md` flips 15-20 more rows to `[x]`
- [ ] One unified architecture log row: "Coverage-axes next-50 — 5-chunk plan complete: N axes + axis_runner + cross-repo wiring; test baseline X → Y"

## Cross-project hand-off note

If chunk 5 spawns a longer cross-repo body of work, it itself becomes a parent plan in semantic-search using the same template. The "Source" field would then chain: `~/workspace/kaizen-md/docs/.../5-chunks.md::chunk-5`.
