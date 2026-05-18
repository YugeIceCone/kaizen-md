# Coverage-axes next-50 — 5-chunk plan

- **Date:** 2026-05-18
- **Scope:** drain the remaining tier-1/2 coverage-axes queue (10 items) + select tier-3 wins (~25), land the generic axis runner (#161) that retrofits the 30 already-shipped axes, then wire the kaizen-* surface into the semantic-search consumer.
- **Projects:** `~/workspace/kaizen-md`, `~/workspace/semantic-search`
- **Source / brainstorm:** `~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl` (lines 1-300)
- **Sibling docs:** `2026-05-18-coverage-checklist.md` (300-row master), `2026-05-18-coverage-loop-implemented.md` (this-run narrative)
- **Total chunks:** 5
- **Concurrency:** **fully parallel** — all 5 chunks dispatch in one message to 5 separate agents. Zero deps between chunks (by isolation contract). A plan-level **Merge step** runs after to consolidate fragments + perform retrofit.
- **Verification cadence:** per-item paired tests + per-chunk full suite + plan-level smoke after merge
- **Template followed:** `docs/superpowers/templates/chunk-plan-template.md` (4-section per-chunk shape + isolation contract + merge step)

## Orchestration

| Chunk | Title                                          | Deps    | Concurrent with | Subagent           | Project          | Worktree branch     | Budget    |
|-------|------------------------------------------------|---------|-----------------|--------------------|------------------|---------------------|-----------|
| 1     | Foundation AST audits                          | —       | 2, 3, 4, 5      | kaizen-implementer | kaizen-md        | `chunk-1-ast`       | ~80 calls |
| 2     | Trace-observability deep-dive                  | —       | 1, 3, 4, 5      | kaizen-implementer | kaizen-md        | `chunk-2-trace`     | ~80 calls |
| 3     | Generic axis runner (#161) — build-only        | —       | 1, 2, 4, 5      | kaizen-implementer | kaizen-md        | `chunk-3-runner`    | ~100 calls|
| 4     | Test quality + mutation gating (standalone)    | —       | 1, 2, 3, 5      | kaizen-implementer | kaizen-md        | `chunk-4-mutation`  | ~70 calls |
| 5     | Cross-project audit using THE 30 PRE-EXISTING  | —       | 1, 2, 3, 4      | general-purpose    | semantic-search  | n/a (different repo)| ~50 calls |
| MERGE | Consolidate fragments + retrofit              | 1,2,3,4,5 | —             | parent orchestrator| kaizen-md + ss   | master              | ~40 calls |

**Dispatch order:**

```python
# Single message — all 5 in parallel (no inter-chunk deps)
[Agent(chunk-1), Agent(chunk-2), Agent(chunk-3),
 Agent(chunk-4), Agent(chunk-5)]

# After all 5 finish — parent runs MERGE step (this plan's `## Merge step` section)
```

**Why this works:** chunks 1-4 each run in their own worktree branch; chunk 5 runs in a different repo. The only files all chunks would normally collide on (`plugin.json`, `progress.md`, `backlog.json`, `gateway.py::SUBSERVERS`) are **fragment-written** to per-chunk `.chunks/N/` dirs. The MERGE step consolidates fragments into the canonical files in a single sequential pass — no concurrent edits ever happen on the canonical files.

---

## Chunk 1: Foundation AST audits

| field        | value                                                                                       |
|--------------|---------------------------------------------------------------------------------------------|
| **Purpose**  | 5 small AST-based code-quality audits, all stdlib-only                                       |
| **Project**  | `~/workspace/kaizen-md`                                                                     |
| **Deps**     | —                                                                                           |
| **Outputs**  | `{fn_name_quality,validator_wiring,mock_real_pairing,iron_law_per_feature,comment_quality}.py` + paired tests + bins + perms |
| **Subagent** | `kaizen-implementer`                                                                        |
| **Isolation**| `worktree`                                                                                  |
| **Budget**   | ~80 tool calls                                                                              |

### Guide

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills to load FIRST (in order):** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`
- **Files to read FIRST (canonical exemplars):**
  - `plugins/kaizen/skills/workflow/scripts/class_name_quality.py` — AST audit shape
  - `plugins/kaizen/skills/workflow/scripts/heavy_imports.py` — AST + module-level filtering
  - `plugins/kaizen/skills/workflow/scripts/subprocess_rc.py` — AST `Visitor` pattern
- **Conventions in this codebase:**
  - `_envelope.emitter("kaizen-<n>", tool_version="1.0.0")` is the output emitter
  - `report` + `gaps` subcommands; `gaps` exits 1 when violations > 0
  - Pure-fn `scan_text(source, *, path) -> list[dict]` for AST scans (so it's unit-testable without disk I/O)
  - **Never** name a script `test_*.py` — it shadows unittest discovery (Boy-Scout from prior session)
- **Upstream decisions that constrain this chunk:**
  - The 30 axes from `2026-05-18-coverage-loop-implemented.md` are already in master — build on top, don't re-do
  - YAGNI-deferred Phase-2 items remain parked (don't pull them in)
- **What NOT to touch:**
  - Vendored skills under `plugins/kaizen/skills/coding-skills/`, `superpowers/`, `remember/` (iron-law `no-modify-vendored`)
  - `gateway.py::SUBSERVERS` (MCP gateway — out of scope for chunk 1)

### Task list (checklist)

- [ ] **C1.A** kaizen-fn-name-quality (#10) — AST: function names start with verb
- [ ] **C1.B** kaizen-validator-wiring (#18) — AST: json.load without .validate call
- [ ] **C1.C** kaizen-mock-real-pairing (#23) — tests that mock X without a `_live.py` sibling
- [ ] **C1.D** kaizen-iron-law-per-feature (#47) — rollup iron-law findings grouped by owning feature
- [ ] **C1.E** kaizen-comment-quality (#1) — rewrite-without-loss heuristic
- [ ] **C1.F** chunk close-out — full suite + arch log row + final commit refs chunk-1

### Plan

| Action  | Path                                                                       | Responsibility                                 |
|---------|----------------------------------------------------------------------------|------------------------------------------------|
| Create  | `plugins/kaizen/skills/workflow/scripts/fn_name_quality.py`                | AST verb-vs-name match                         |
| Create  | `plugins/kaizen/skills/workflow/scripts/validator_wiring.py`               | AST: json.load + no .validate                  |
| Create  | `plugins/kaizen/skills/workflow/scripts/mock_real_pairing.py`              | mock.patch w/o sibling `_live.py`              |
| Create  | `plugins/kaizen/skills/workflow/scripts/iron_law_per_feature.py`           | rollup iron-laws JSON by feature dir           |
| Create  | `plugins/kaizen/skills/workflow/scripts/comment_quality.py`                | comment-vs-code redundancy heuristic           |
| Create  | `plugins/kaizen/tests/test_<each>.py` (×5)                                 | paired tests                                   |
| Symlink | `plugins/kaizen/bin/kaizen-<each>` (×5) → `../skills/workflow/scripts/...` | bin wrappers                                   |
| Write   | `.chunks/1/perms.json`                                                     | 10 perm entries (5 script + 5 bin) — fragment  |
| Write   | `.chunks/1/progress.md`                                                    | architecture log row — fragment                |

### Isolation contract

**Owns (exclusive write):**
- `plugins/kaizen/skills/workflow/scripts/{fn_name_quality,validator_wiring,mock_real_pairing,iron_law_per_feature,comment_quality}.py`
- `plugins/kaizen/tests/test_{fn_name_quality,validator_wiring,mock_real_pairing,iron_law_per_feature,comment_quality}.py`
- `plugins/kaizen/bin/kaizen-{fn-name-quality,validator-wiring,mock-real-pairing,iron-law-per-feature,comment-quality}` (5 NEW symlinks)
- `.chunks/1/` (fragment dir — single-writer)

**Reads only (NEVER writes):**
- `plugins/kaizen/.claude-plugin/plugin.json` — perm entries → `.chunks/1/perms.json` instead
- `.kaizen/workflow/progress.md` — arch row → `.chunks/1/progress.md` instead
- `.kaizen/workflow/backlog.json` — none for this chunk
- Any file matching chunks 2-4's exclusive list (different script names — no overlap by design)

**Worktree:** runs in `.claude/worktrees/chunk-1-ast/`. Final commit on branch `chunk-1-ast` → merged by orchestrator into master before the MERGE step.

### TDD code chunks

#### item C1.A — kaizen-fn-name-quality (#10)

**RED test** (`tests/test_fn_name_quality.py`):
```python
def test_get_user_starts_with_verb(self):
    findings = fn_name_quality.scan_text("def get_user(): pass\n", path="ok.py")
    self.assertEqual(findings, [])

def test_user_data_missing_verb(self):
    findings = fn_name_quality.scan_text("def user_data(): pass\n", path="bad.py")
    self.assertEqual(findings[0]["rule"], "no-leading-verb")
```

Run: `cd plugins/kaizen && python3 -m unittest tests.test_fn_name_quality -v`
Expected: FAIL — `ModuleNotFoundError: fn_name_quality`.

**GREEN impl outline** (`skills/workflow/scripts/fn_name_quality.py`):
- Public API: `scan_text(source: str, *, path: str) -> list[dict]`, `scan(*, scripts_dir: Path) -> dict`
- Algorithm: AST walk top-level FunctionDefs; split name on `_`; first part must be in known-verb list (`get/set/build/parse/load/save/run/scan/find/...`). Flag missing-verb names.
- Reuses: `_envelope` for output

**Commit:** `feat(fn-name-quality): AST verb-vs-name check (chunk 1 item A)`

#### item C1.B — kaizen-validator-wiring (#18)

**RED test** (`tests/test_validator_wiring.py`):
```python
def test_load_without_validate_flagged(self):
    src = 'import json\nwith open("x.json") as f: schema = json.load(f)\n'
    findings = validator_wiring.scan_text(src, path="bad.py")
    self.assertTrue(any(f["rule"] == "loads-but-no-validate" for f in findings))

def test_load_with_validate_ok(self):
    src = ('import json\nfrom jsonschema import validate\n'
           'schema = json.load(open("x.json"))\nvalidate(data, schema)\n')
    findings = validator_wiring.scan_text(src, path="ok.py")
    self.assertEqual(findings, [])
```

Run: same shape as A.
Expected: FAIL on missing module.

**GREEN impl outline** (`skills/workflow/scripts/validator_wiring.py`):
- AST visit `json.load(...)` calls; collect their parent scope
- For each scope: check whether a `validate(...)` call OR `.validate(...)` method appears
- Flag scopes with `json.load` but no `validate`
- Reuses: `_envelope`, stdlib `ast`

**Commit:** `feat(validator-wiring): AST scan for orphan schema loads (chunk 1 item B)`

#### item C1.C — kaizen-mock-real-pairing (#23)

**RED test** (`tests/test_mock_real_pairing.py`):
```python
def test_mock_without_live_flagged(self):
    src = "from unittest import mock\nmock.patch('myapp.api.fetch')\n"
    findings = mock_real_pairing.scan_text(src, path="test_a.py",
                                            sibling_live_files=set())
    self.assertTrue(any("fetch" in f["target"] for f in findings))

def test_mock_with_live_sibling_ok(self):
    src = "from unittest import mock\nmock.patch('myapp.api.fetch')\n"
    findings = mock_real_pairing.scan_text(src, path="test_a.py",
                                            sibling_live_files={"test_a_live.py"})
    self.assertEqual(findings, [])
```

**GREEN impl outline:**
- AST visit `mock.patch(...)` Call nodes; extract first arg's string value (the patched target)
- Compare with `sibling_live_files` set (caller supplies — usually `{*_live.py in same dir}`)
- Flag mocked targets without a `_live.py` companion
- Reuses: `_envelope`

**Commit:** `feat(mock-real-pairing): flag mocked targets w/o live counterpart (chunk 1 item C)`

#### item C1.D — kaizen-iron-law-per-feature (#47)

**RED test** (`tests/test_iron_law_per_feature.py`):
```python
def test_rollup_by_feature_dir(self):
    findings = [
        {"path": "skills/brainstorming/SKILL.md", "rule_id": "x", "severity": "warn"},
        {"path": "skills/brainstorming/domain/y.yaml", "rule_id": "z", "severity": "error"},
        {"path": "skills/workflow/scripts/foo.py", "rule_id": "x", "severity": "warn"},
    ]
    rollup = iron_law_per_feature.rollup_by_feature(findings)
    self.assertEqual(rollup["brainstorming"]["total"], 2)
    self.assertEqual(rollup["workflow"]["total"], 1)
```

**GREEN impl outline:**
- Pure fn `rollup_by_feature(findings: list[dict]) -> dict[str, dict]`
- Key by `path.split("/")[1]` (the feature dir under `skills/`)
- Aggregate `{total, by_severity{}, by_rule{}}`
- CLI subcommand `report` shells out to `kaizen-iron-laws check --json`, feeds result to rollup, emits envelope
- Reuses: `_envelope`, `subprocess.run(check=True)`

**Commit:** `feat(iron-law-per-feature): rollup iron-law findings by feature (chunk 1 item D)`

#### item C1.E — kaizen-comment-quality (#1)

**RED test** (`tests/test_comment_quality.py`):
```python
def test_redundant_comment_flagged(self):
    src = "# increment counter\ncounter += 1\n"
    findings = comment_quality.scan_text(src, path="bad.py")
    self.assertTrue(any(f["rule"] == "redundant-comment" for f in findings))

def test_explanatory_comment_ok(self):
    src = "# guard against legacy 0.x state\nif legacy_state(): handle()\n"
    findings = comment_quality.scan_text(src, path="ok.py")
    self.assertEqual(findings, [])
```

**GREEN impl outline:**
- Tokenize comment text (lowercase, strip stopwords)
- Tokenize next non-comment code line (identifiers, split on `_`)
- If comment tokens ⊆ code tokens (Jaccard ≥0.8) → flag `redundant-comment`
- Reuses: `_envelope`, stdlib `tokenize`

**Commit:** `feat(comment-quality): rewrite-without-loss heuristic (chunk 1 item E)`

#### item C1.F — chunk close-out

**RED:** `cd plugins/kaizen && python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3` — expect `OK`, NO failures.

**GREEN:**
1. Write fragment `.chunks/1/perms.json` (10 entries — 5 script + 5 bin perms in `Bash(...)` format).
2. Write fragment `.chunks/1/progress.md` containing the single arch-log row:
   ```
   | 2026-05-18 | feat | +~X -0 | Chunk 1 — 5 foundation AST axes (fn-name / validator-wiring / mock-real / iron-law-per-feature / comment-quality). Test baseline 3153 → ~3175 (+~22). Refs: docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-1 |
   ```
3. Do NOT edit `.claude-plugin/plugin.json` or `.kaizen/workflow/progress.md` — the MERGE step consolidates fragments.

**Commit:** `chore(chunk-1): close-out — 5 foundation AST axes + fragments (Refs: docs/.../5-chunks.md::chunk-1)`

### Done when:

- [ ] All 5 axes green + bin + perm + paired test
- [ ] `python3 -m unittest discover` — 0 regressions on the prior 3153
- [ ] Architecture log row appended
- [ ] Each commit names `chunk 1 item X`
- [ ] Close-out commit references downstream `chunk-3` (which depends on this)

### Dispatch (paste-ready)

```python
Agent(
    description="Coverage-axes chunk 1 — Foundation AST audits",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 1 of docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md.

WORKING DIR: /home/cherry86/workspace/kaizen-md

READ FIRST (in order):
1. docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-1
2. docs/superpowers/templates/chunk-plan-template.md (the 4-section shape)
3. plugins/kaizen/skills/workflow/scripts/class_name_quality.py (canonical AST-axis exemplar)

SKILLS TO LOAD (before any edit): kaizen:tdd, kaizen:plugin-development

EXECUTE: the Task list (checklist), items C1.A → C1.F in order. Each is a (RED → GREEN → commit) triple per the TDD code chunks block. Never:
  - skip RED-then-GREEN verification
  - bundle items into one commit
  - modify outside the Plan file inventory without flagging
  - name a script `test_*.py` (shadow unittest discovery — prior Boy-Scout lesson)

DONE WHEN: every paired test green, full suite 0 regressions, arch log row appended, close-out commit references chunk-1.

BUDGET: ~80 tool calls. If exhausted: commit green items + write chunk-1-resume.md."""
)
```

---

## Chunk 2: Trace-observability deep-dive

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | per-feature lifecycle audit + cross-index joins (trace + token-bloat) + substrate refactor           |
| **Project**  | `~/workspace/kaizen-md`                                                                              |
| **Deps**     | —                                                                                                    |
| **Outputs**  | `{lifecycle_audit,trace_bloat_join,stream_join,append_to_universal}.py` + tests + bins + perms       |
| **Subagent** | `kaizen-implementer`                                                                                 |
| **Isolation**| `worktree`                                                                                           |
| **Budget**   | ~80 tool calls                                                                                       |

### Guide

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills to load FIRST:** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`
- **Files to read FIRST (canonical exemplars):**
  - `plugins/kaizen/skills/workflow/scripts/turn_density.py` — trace-JSONL read shape
  - `plugins/kaizen/skills/workflow/scripts/prompt_event_diff.py` — UserPromptSubmit slicing
  - `plugins/kaizen/skills/workflow/scripts/silent_fail.py` — graceful trace-log-missing path
  - `plugins/kaizen/skills/workflow/scripts/_atomic.py::atomic_append_line` — the canonical append helper
- **Conventions:**
  - Trace log: `~/.claude/.kaizen/trace/events.jsonl` (per `_paths.py`)
  - Token-bloat data: `~/.claude/.kaizen/token-bloat/*.jsonl`
  - Always have `trace_log not found` graceful path returning `{"...": [], "note": "..."}`
  - Subcommands `report` (envelope) + `gaps` (one-line per finding)
- **Upstream decisions:**
  - `_atomic.atomic_append_line` is the SSOT for JSONL appends — chunk 2 audits emitters that bypass it
  - JSONL session_id field name varies (`session_id`, `sid`, `session`) — normalize on read
- **What NOT to touch:**
  - The trace event schema itself (it evolves elsewhere)
  - `_atomic.py` (audit, don't refactor — leave the refactor itself as a separate chunk)

### Task list (checklist)

- [ ] **C2.A** kaizen-lifecycle-audit (#57) — git+trace timeline for a feature name
- [ ] **C2.B** kaizen-trace-bloat-join (#92) — join trace + token-bloat on session_id
- [ ] **C2.C** kaizen-stream-join (#153) — CLI: stream-join trace + dxm on session_id
- [ ] **C2.D** kaizen-append-to-audit (#151) — AST scan for emitters that bypass `_atomic.atomic_append_line`
- [ ] **C2.E** chunk close-out — full suite + arch log row + final commit refs chunk-2

### Plan

| Action  | Path                                                              | Responsibility                                     |
|---------|-------------------------------------------------------------------|----------------------------------------------------|
| Create  | `plugins/kaizen/skills/workflow/scripts/lifecycle_audit.py`       | git log + trace events for a feature name          |
| Create  | `plugins/kaizen/skills/workflow/scripts/trace_bloat_join.py`      | inner-join on session_id                           |
| Create  | `plugins/kaizen/skills/workflow/scripts/stream_join.py`           | sorted-merge of trace + dxm streams                |
| Create  | `plugins/kaizen/skills/workflow/scripts/append_to_audit.py`       | AST scan for ad-hoc append patterns                |
| Create  | `plugins/kaizen/tests/test_<each>.py` (×4)                        | paired tests                                       |
| Symlink | `plugins/kaizen/bin/kaizen-<each>` (×4)                           | bin wrappers                                       |
| Write   | `.chunks/2/perms.json`                                            | 8 perm entries — fragment                          |
| Write   | `.chunks/2/progress.md`                                           | architecture log row — fragment                    |

### Isolation contract

**Owns (exclusive write):**
- `plugins/kaizen/skills/workflow/scripts/{lifecycle_audit,trace_bloat_join,stream_join,append_to_audit}.py`
- `plugins/kaizen/tests/test_{lifecycle_audit,trace_bloat_join,stream_join,append_to_audit}.py`
- `plugins/kaizen/bin/kaizen-{lifecycle-audit,trace-bloat-join,stream-join,append-to-audit}` (4 NEW symlinks)
- `.chunks/2/` (fragment dir — single-writer)

**Reads only (NEVER writes):**
- `plugins/kaizen/.claude-plugin/plugin.json` — perms → `.chunks/2/perms.json`
- `.kaizen/workflow/progress.md` — arch row → `.chunks/2/progress.md`
- `plugins/kaizen/skills/workflow/scripts/_atomic.py` — audit-only, refactor deferred to MERGE step
- Any file matching chunks 1, 3, 4's exclusive lists (zero overlap by design)

**Worktree:** runs in `.claude/worktrees/chunk-2-trace/`. Final commit on branch `chunk-2-trace` → orchestrator merges to master before MERGE step.

### TDD code chunks

#### item C2.A — kaizen-lifecycle-audit (#57)

**RED test** (`tests/test_lifecycle_audit.py`):
```python
def test_merges_git_and_trace(self):
    git_rows = [{"ts": "2026-05-18T10:00", "kind": "commit", "summary": "feat(x): y"}]
    trace_rows = [{"ts": "2026-05-18T10:30", "kind": "tool_use", "summary": "Read(x.py)"}]
    timeline = lifecycle_audit.merge_timeline(git_rows, trace_rows)
    self.assertEqual(len(timeline), 2)
    self.assertLessEqual(timeline[0]["ts"], timeline[1]["ts"])
```

**GREEN impl outline:**
- Pure `merge_timeline(git, trace) -> list[dict]` sorted by `ts`
- CLI `scan(feature_name)`: runs `git log --grep=<feature> --format=%cI|%s`, greps trace JSONL for events mentioning the feature, merges
- Reuses: `_envelope`, `subprocess.run`

**Commit:** `feat(lifecycle-audit): per-feature git+trace timeline (chunk 2 item A)`

#### item C2.B — kaizen-trace-bloat-join (#92)

**RED test** (`tests/test_trace_bloat_join.py`):
```python
def test_inner_join_on_session_id(self):
    trace = [{"session_id": "s1", "event_count": 5}, {"session_id": "s2", "event_count": 3}]
    bloat = [{"session_id": "s1", "tokens_wasted": 1000}]
    joined = trace_bloat_join.join(trace, bloat)
    self.assertEqual(len(joined), 1)  # s1 only — s2 has no bloat row
    self.assertEqual(joined[0]["tokens_wasted"], 1000)
```

**GREEN impl outline:**
- Pure `join(trace_rows, bloat_rows) -> list[dict]` — index bloat by session_id, walk trace, merge
- CLI loads both JSONL inputs, calls join, emits envelope
- Reuses: `_envelope`

**Commit:** `feat(trace-bloat-join): join trace + token-bloat on session_id (chunk 2 item B)`

#### item C2.C — kaizen-stream-join (#153)

**RED test** (`tests/test_stream_join.py`):
```python
def test_sorted_merge_two_streams(self):
    trace = [{"ts": 100, "kind": "trace", "x": "a"}, {"ts": 300, "kind": "trace", "x": "c"}]
    dxm   = [{"ts": 200, "kind": "dxm",   "x": "b"}]
    merged = stream_join.sorted_merge(trace, dxm, key="ts")
    self.assertEqual([r["x"] for r in merged], ["a", "b", "c"])
```

**GREEN impl outline:**
- Pure `sorted_merge(*streams, key) -> list[dict]` — `heapq.merge`-based
- CLI: `--trace PATH --dxm PATH --session SID` filters each stream to session, merges, emits
- Reuses: `_envelope`, stdlib `heapq`

**Commit:** `feat(stream-join): merge trace + dxm on session_id (chunk 2 item C)`

#### item C2.D — kaizen-append-to-audit (#151)

**RED test** (`tests/test_append_to_audit.py`):
```python
def test_open_a_mode_flagged(self):
    src = 'with open("x.jsonl", "a") as f:\n    f.write(line)\n'
    findings = append_to_audit.scan_text(src, path="bad.py")
    self.assertTrue(any(f["rule"] == "ad-hoc-append" for f in findings))

def test_atomic_append_line_ok(self):
    src = 'from _atomic import atomic_append_line\natomic_append_line("x.jsonl", line)\n'
    findings = append_to_audit.scan_text(src, path="ok.py")
    self.assertEqual(findings, [])
```

**GREEN impl outline:**
- AST visit `open(...)` Call nodes; check 2nd arg or `mode=` kw for `"a"` / `"ab"`
- Flag any `open(*, "a")` that isn't already wrapped by `atomic_append_line` (heuristic: file uses `open("...", "a")` AND doesn't import `_atomic`)
- Reuses: `_envelope`

**Commit:** `feat(append-to-audit): AST scan for ad-hoc append patterns (chunk 2 item D)`

#### item C2.E — chunk close-out

Same shape as C1.F: full suite + architecture log row + commit refs `chunk-2`.

### Done when:

- [ ] 4 axes green + paired tests + bins + perms
- [ ] Full suite 0 regressions
- [ ] Architecture log row appended
- [ ] Close-out commit references downstream `chunk-3`

### Dispatch (paste-ready)

```python
Agent(
    description="Coverage-axes chunk 2 — Trace observability",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 2 (parallel with chunk 1). Same 4-section shape as the template.

WORKING DIR: /home/cherry86/workspace/kaizen-md

READ FIRST (in order):
1. docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-2
2. docs/superpowers/templates/chunk-plan-template.md (the 4-section shape)
3. plugins/kaizen/skills/workflow/scripts/turn_density.py (canonical trace-axis exemplar)

SKILLS: kaizen:tdd, kaizen:plugin-development

EXECUTE: Task list (checklist) C2.A → C2.E. Per-item RED → GREEN → commit. Iron Laws as in chunk 1.

DONE WHEN: 4 axes green, 0 regressions, arch log row, close-out commit references chunk-2 + downstream chunk-3.

BUDGET: ~80 tool calls."""
)
```

---

## Chunk 3: Generic axis runner (#161) — build-only (retrofit deferred to MERGE step)

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | Build the declarative `axis-as-yaml` runner + 1 reference YAML axis as proof. **No retrofit of existing axes here** — that's done by the MERGE step after chunks 1+2's axes also land. Keeps chunk 3 fully independent. |
| **Project**  | `~/workspace/kaizen-md`                                                                              |
| **Deps**     | —                                                                                                    |
| **Outputs**  | `axis_runner.py` + `axis.schema.json` + 1 reference YAML axis + `axis_runner_rules.py` (rule lib for grep / ast-rule / file-coverage dispatch) |
| **Subagent** | `kaizen-implementer`                                                                                 |
| **Isolation**| `worktree`                                                                                           |
| **Budget**   | ~100 tool calls                                                                                      |

### Guide

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills to load FIRST:** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`, `Skill(kaizen:decision-rubric)` (the YAML-walker pattern this generalizes)
- **Files to read FIRST:**
  - `plugins/kaizen/skills/workflow/scripts/schema_cli.py::BucketWalker` — the YAML-walker exemplar
  - 3-4 of the 30 shipped axes — note their common shape (`scan(...) → dict`, gaps subcommand, envelope emit)
  - `plugins/kaizen/skills/handoff/domain/outcome-rubric.yaml` — exemplar of data-driven YAML config
- **Conventions:**
  - Axis YAML lives at `skills/<feature>/domain/axes/<name>.yaml`
  - The runner picks ALL `**/domain/axes/*.yaml` at startup; no manual registration
  - Output stays canonical-envelope shape (so all clients still parse the same)
- **Upstream decisions:**
  - YAML schema design is load-bearing — write `axis.schema.json` FIRST and self-review before any runner code
  - Ship 1 reference YAML axis (`reference_demo.yaml`) as proof; **the MERGE step** handles retrofitting any of the 30 already-shipped axes plus chunks 1+2 outputs
- **What NOT to touch:**
  - Any existing `.py` axis (the retrofit is deferred to MERGE)
  - `gateway.py::SUBSERVERS` — axis_runner_mcp mounting goes via `.chunks/3/mcp-mounts.txt` fragment
  - Files owned by chunks 1, 2, 4 (different paths — no overlap)

### Isolation contract

**Owns (exclusive write):**
- `plugins/kaizen/skills/workflow/scripts/{axis_runner,axis_runner_rules,axis_runner_mcp}.py` (3 NEW)
- `plugins/kaizen/skills/workflow/domain/schemas/axis.schema.json` (NEW)
- `plugins/kaizen/skills/workflow/domain/axes/reference_demo.yaml` (NEW — proof axis)
- `plugins/kaizen/tests/test_{axis_runner,axis_runner_rules}.py` (2 NEW)
- `plugins/kaizen/bin/kaizen-axis-runner` (1 NEW symlink)
- `.chunks/3/` (fragment dir)

**Reads only (NEVER writes):**
- `plugins/kaizen/.claude-plugin/plugin.json` — perms → `.chunks/3/perms.json`
- `.kaizen/workflow/progress.md` — arch row → `.chunks/3/progress.md`
- `.kaizen/workflow/backlog.json` — `BK-NNN` parking items → `.chunks/3/backlog.jsonl`
- `gateway.py::SUBSERVERS` — MCP mount → `.chunks/3/mcp-mounts.txt`
- The 30 already-shipped axes (read for shape extraction, never modified)
- Files owned by chunks 1, 2, 4 (no overlap)

**Worktree:** `.claude/worktrees/chunk-3-runner/`. Branch `chunk-3-runner` → orchestrator merges to master before MERGE step.

### Task list (checklist)

- [ ] **C3.A** Design `axis.schema.json` (and self-review against the 30 already-shipped axes for fit)
- [ ] **C3.B** RED test: `axis_runner.load(yaml_path) → run() → envelope shape`
- [ ] **C3.C** GREEN: `axis_runner.py` — dispatches by `scan-spec.type` (grep / ast-rule / file-coverage)
- [ ] **C3.D** Retrofit `md_whitespace` as YAML; delete the `.py`; suite green
- [ ] **C3.E** Retrofit 4 more grep-style axes (md_dupes / md_heading_depth / todo_inventory / unused_env)
- [ ] **C3.D** Build `axis_runner_rules.py` — the rule lib (grep / ast-rule / file-coverage dispatchers)
- [ ] **C3.E** Ship 1 reference YAML axis (`reference_demo.yaml`) using grep dispatcher — proof of subsumption
- [ ] **C3.F** Build `axis_runner_mcp.py` — fragment-write its mount line to `.chunks/3/mcp-mounts.txt` (MERGE step wires SUBSERVERS)
- [ ] **C3.G** chunk close-out — full suite + fragments (perms.json + progress.md + backlog.jsonl with BK-NNN retrofit-pending parks)

### Plan

| Action  | Path                                                                          | Responsibility                                  |
|---------|-------------------------------------------------------------------------------|-------------------------------------------------|
| Create  | `plugins/kaizen/skills/workflow/domain/schemas/axis.schema.json`              | JSON Schema for axis YAML                       |
| Create  | `plugins/kaizen/skills/workflow/scripts/axis_runner.py`                       | YAML loader + dispatcher                        |
| Create  | `plugins/kaizen/skills/workflow/scripts/axis_runner_rules.py`                 | grep / ast-rule / file-coverage rule lib        |
| Create  | `plugins/kaizen/skills/workflow/scripts/axis_runner_mcp.py`                   | MCP wrapper (mount via fragment)                |
| Create  | `plugins/kaizen/skills/workflow/domain/axes/reference_demo.yaml`              | proof-of-subsumption YAML axis                  |
| Create  | `plugins/kaizen/tests/test_axis_runner.py` + `test_axis_runner_rules.py`      | paired tests                                    |
| Symlink | `plugins/kaizen/bin/kaizen-axis-runner` → `../skills/.../axis_runner.py`      | bin wrapper (NEW only)                          |
| Write   | `.chunks/3/perms.json`                                                        | runner perm + bin perm + mcp perm — fragment    |
| Write   | `.chunks/3/progress.md`                                                       | arch row — fragment                             |
| Write   | `.chunks/3/backlog.jsonl`                                                     | 25-30 BK-NNN retrofit-pending parks — fragment  |
| Write   | `.chunks/3/mcp-mounts.txt`                                                    | one line `("axis_runner", "axis_runner_mcp")`   |

**RETROFIT IS NOT IN THIS CHUNK.** It lands in the MERGE step at plan-end, which has visibility to all 30 already-shipped axes + chunk 1 + chunk 2 outputs together.

### TDD code chunks

#### item C3.A — design axis.schema.json

**RED:** write the schema then `kaizen-iron-laws` should accept it as a domain schema (no validator error).

**GREEN outline (`domain/schemas/axis.schema.json`):**
```json
{
  "title": "kaizen axis declaration",
  "required": ["name", "scan_spec", "verdict_rule"],
  "properties": {
    "name":        {"type": "string"},
    "description": {"type": "string"},
    "scan_spec": {
      "oneOf": [
        {"type": "object", "properties": {"type": {"const": "grep"},        "pattern": {"type": "string"},     "glob": {"type": "string"}}, "required": ["type", "pattern", "glob"]},
        {"type": "object", "properties": {"type": {"const": "ast-rule"},    "rule": {"type": "string"},        "glob": {"type": "string"}}, "required": ["type", "rule", "glob"]},
        {"type": "object", "properties": {"type": {"const": "file-coverage"}, "expected_glob": {"type": "string"}, "actual_glob": {"type": "string"}}, "required": ["type", "expected_glob", "actual_glob"]}
      ]
    },
    "verdict_rule": {
      "properties": {"green_max": {"type": "integer"}, "yellow_max": {"type": "integer"}}
    }
  },
  "additionalProperties": false
}
```

**Commit:** `feat(axis): axis.schema.json — declarative axis contract (chunk 3 item A)`

#### item C3.B — RED test for axis_runner

**RED test** (`tests/test_axis_runner.py`):
```python
def test_load_and_run_grep_axis(self):
    with tempfile.TemporaryDirectory() as td:
        axis = Path(td) / "axis.yaml"
        axis.write_text(
            'name: trailing-ws\nscan_spec:\n  type: grep\n  pattern: " $"\n  glob: "*.md"\n'
            'verdict_rule: {green_max: 0, yellow_max: 10}\n')
        (Path(td) / "a.md").write_text("trailing  \n")
        result = axis_runner.run_axis(axis, root=Path(td))
        self.assertEqual(result["verdict"], "yellow")  # 1 finding > 0
        self.assertEqual(len(result["findings"]), 1)
```

Expected: FAIL — `axis_runner` doesn't exist.

#### item C3.C — GREEN axis_runner

**GREEN outline:**
- `load(yaml_path) -> AxisSpec` — parses + validates against schema
- `run_axis(yaml_path, *, root) -> dict` — dispatches by `scan_spec.type`:
  - `grep` → walk glob, regex per line, collect findings
  - `ast-rule` → walk glob, AST parse, apply named rule (rule lib in `axis_runner_rules.py`)
  - `file-coverage` → set-diff between `expected_glob` matches and `actual_glob` matches
- Verdict computed from `verdict_rule` thresholds against finding count
- Reuses: `_envelope`, `jsonschema` (graceful when not installed)

**Commit:** `feat(axis-runner): YAML axis loader + 3 scan-spec types (chunk 3 item C)`

#### item C3.D — axis_runner_rules.py (rule lib)

**RED test** (`tests/test_axis_runner_rules.py`):
```python
def test_grep_rule_finds_trailing_ws(self):
    findings = axis_runner_rules.run_grep(pattern=r" $", glob="*.md",
                                            root=tmpdir_with_trailing_ws)
    self.assertEqual(len(findings), 1)
```

**GREEN outline:** module exposes `run_grep(pattern, glob, root) -> list[dict]`, `run_ast_rule(rule, glob, root, params) -> list`, `run_file_coverage(expected_glob, actual_glob, root) -> list`. Pure-fn rule library; `axis_runner.py` dispatches into here by `scan_spec.type`.

**Commit:** `feat(axis-runner): rule lib for 3 scan-spec types (chunk 3 item D)`

#### item C3.E — reference_demo.yaml (proof axis)

**RED:** axis YAML must validate against `axis.schema.json` AND produce one finding when run against a synthetic input with one trailing-whitespace line.

**GREEN outline** (`domain/axes/reference_demo.yaml`):
```yaml
name: reference-demo-trailing-ws
description: proof-of-concept YAML axis (subsumed by axis_runner)
scan_spec:
  type: grep
  pattern: " +$"
  glob: "**/*.md"
verdict_rule:
  green_max: 0
  yellow_max: 10
```

**Commit:** `feat(axis-runner): reference_demo.yaml proof axis (chunk 3 item E)`

#### item C3.F — axis_runner_mcp.py + mount-fragment

**RED test:** `axis_runner_mcp.list_axes()` returns ≥1 axis entry.

**GREEN outline:** standard FastMCP server pattern (mirror `metrics_mcp.py`); expose `list_axes()`, `run_axis(name)`, `report(name)` tools. Write `("axis_runner", "axis_runner_mcp")` to `.chunks/3/mcp-mounts.txt` so MERGE step appends to `gateway.py::SUBSERVERS`.

**Commit:** `feat(axis-runner): MCP wrapper + mount-fragment (chunk 3 item F)`

#### item C3.G — chunk close-out

**RED:** `cd plugins/kaizen && python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3` — expect OK, no failures.

**GREEN:**
1. Write `.chunks/3/perms.json` (3 entries: runner script + bin + mcp script).
2. Write `.chunks/3/progress.md` (one arch row naming "axis_runner build-only, retrofit deferred to MERGE").
3. Write `.chunks/3/backlog.jsonl` with BK-NNN entries for each candidate retrofit (30 already-shipped + chunks 1-2 outputs become BK-NNN after MERGE inventory). Each row: `{"title": "Retrofit <axis> to YAML", "section": "parked", "verify": "kaizen-axis-runner run --axis <name> ⇒ same findings as legacy", ...}`.

**Commit:** `chore(chunk-3): close-out — axis_runner shipped + fragments (Refs: docs/.../5-chunks.md::chunk-3)`

### Done when:

- [ ] `axis_runner.py` + `axis_runner_rules.py` + `axis_runner_mcp.py` ship green
- [ ] `axis.schema.json` validates `reference_demo.yaml`
- [ ] `reference_demo.yaml` runs through the runner and produces expected findings
- [ ] `.chunks/3/{perms.json, progress.md, backlog.jsonl, mcp-mounts.txt}` all present
- [ ] **NO retrofit performed** — that's the MERGE step's job
- [ ] 0 regressions on the prior 3153

### Dispatch (paste-ready)

```python
Agent(
    description="Coverage-axes chunk 3 — Generic axis runner (#161)",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 3. Deps 1+2 must be complete — assert by checking git log mentions `chunk-1` and `chunk-2`.

WORKING DIR: /home/cherry86/workspace/kaizen-md

READ FIRST (in order):
1. docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-3
2. docs/superpowers/templates/chunk-plan-template.md
3. plugins/kaizen/skills/workflow/scripts/schema_cli.py::BucketWalker (YAML-walker exemplar)
4. 3-4 of the 30 already-shipped axes — extract the common shape

SKILLS: kaizen:tdd, kaizen:plugin-development, kaizen:decision-rubric

DESIGN GATE: write axis.schema.json FIRST (item C3.A) and pause to self-review against the 30 shipped axes for fit before any runner code.

EXECUTE: Task list (checklist) C3.A → C3.G. Per-item RED → GREEN → commit. Iron Laws as in chunk 1.

NEVER write to: plugin.json, .kaizen/workflow/progress.md, .kaizen/workflow/backlog.json, or gateway.py::SUBSERVERS. All shared-file mutations go to .chunks/3/ fragments. The MERGE step (run by parent after chunk 3 finishes) consolidates fragments.

BUDGET: ~100 tool calls.
DONE WHEN: runner + rules lib + mcp + reference yaml all green, .chunks/3/* fragments present, 0 regressions."""
)
```

---

## Chunk 4: Test quality + mutation gating (standalone — no axis-runner dep)

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | Mutation testing (#24 mutmut) + 3 standalone Python test-quality axes (assertion-density, parametrize-coverage, error-path-coverage). Built as classic Python axes for independence — MERGE step retrofits them to YAML alongside the other 30+. |
| **Project**  | `~/workspace/kaizen-md`                                                                              |
| **Deps**     | —                                                                                                    |
| **Outputs**  | `{mutation_gate,assertion_density,parametrize_coverage,error_path_coverage}.py` + tests + bins       |
| **Subagent** | `kaizen-implementer`                                                                                 |
| **Isolation**| `worktree`                                                                                           |
| **Budget**   | ~70 tool calls                                                                                       |

### Guide

- **Working dir:** `/home/cherry86/workspace/kaizen-md`
- **Skills to load FIRST:** `Skill(kaizen:tdd)`, `Skill(kaizen:plugin-development)`
- **Files to read FIRST:**
  - `plugins/kaizen/skills/workflow/scripts/dead_code.py` (graceful-skip-when-dep-missing template)
  - `plugins/kaizen/skills/workflow/scripts/class_name_quality.py` (AST scan template — same shape as the 3 standalone axes)
- **Conventions:**
  - mutmut isn't installed by default — same `is_available()` + graceful-fallback shape as `dead_code.py`
  - Build the 3 quality axes as classic Python (NOT axis_runner YAML) — keeps chunk 4 free of chunk 3 dep
- **Upstream decisions:**
  - Mutation kill-ratio target: ≥80% on the file(s) under test
  - Don't run mutmut in CI by default — opt-in via `KAIZEN_MUTATION_TEST_LIVE=1`
  - Convert these 3 axes to YAML form during the MERGE step (after axis_runner from chunk 3 is available)
- **What NOT to touch:**
  - Existing test files (mutation tests are read-only against tests/)
  - axis_runner / axis_runner_rules (chunk 3's output — DO NOT consume during chunk 4)
  - Files owned by chunks 1, 2, 3, 5

### Isolation contract

**Owns (exclusive write):**
- `plugins/kaizen/skills/workflow/scripts/{mutation_gate,assertion_density,parametrize_coverage,error_path_coverage}.py`
- `plugins/kaizen/tests/test_{mutation_gate,assertion_density,parametrize_coverage,error_path_coverage}.py`
- `plugins/kaizen/bin/kaizen-{mutation-gate,assertion-density,parametrize-coverage,error-path-coverage}` (4 NEW symlinks)
- `.chunks/4/` (fragment dir)

**Reads only (NEVER writes):**
- `plugins/kaizen/.claude-plugin/plugin.json` — perms → `.chunks/4/perms.json`
- `.kaizen/workflow/progress.md` — arch row → `.chunks/4/progress.md`
- Files owned by chunks 1, 2, 3, 5

**Worktree:** `.claude/worktrees/chunk-4-mutation/`. Branch `chunk-4-mutation` → orchestrator merges to master before MERGE step.

### Task list (checklist)

- [ ] **C4.A** kaizen-mutation-gate (#24) — mutmut wrapper, graceful-skip, target ≥80% kill ratio
- [ ] **C4.B** assertion-density axis (yaml-decl) — tests with body but no `self.assert*`
- [ ] **C4.C** parametrize-coverage axis (yaml-decl) — repeated near-identical test bodies
- [ ] **C4.D** error-path-coverage axis (yaml-decl) — scripts that `raise` but no test catches the exception
- [ ] **C4.E** chunk close-out — full suite + arch log row + final commit refs chunk-4

### Plan

| Action  | Path                                                                            | Responsibility                                  |
|---------|---------------------------------------------------------------------------------|-------------------------------------------------|
| Create  | `plugins/kaizen/skills/workflow/scripts/mutation_gate.py`                       | mutmut wrapper + kill-ratio gate                |
| Create  | `plugins/kaizen/skills/workflow/scripts/assertion_density.py`                   | AST scan — test methods missing assert calls    |
| Create  | `plugins/kaizen/skills/workflow/scripts/parametrize_coverage.py`                | AST scan — repeated near-identical test bodies  |
| Create  | `plugins/kaizen/skills/workflow/scripts/error_path_coverage.py`                 | AST scan — raises with no test catching them    |
| Create  | `plugins/kaizen/tests/test_<each>.py` (×4)                                      | paired tests                                    |
| Symlink | `plugins/kaizen/bin/kaizen-<each>` (×4) → `../skills/workflow/scripts/...`      | bin wrappers (4 NEW)                            |
| Write   | `.chunks/4/perms.json`                                                          | 8 perm entries — fragment                       |
| Write   | `.chunks/4/progress.md`                                                         | arch row — fragment                             |
| Write   | `.chunks/4/backlog.jsonl`                                                       | 4 BK-NNN entries: "retrofit <axis> to YAML"     |

### TDD code chunks

#### item C4.A — kaizen-mutation-gate (#24)

**RED test** (`tests/test_mutation_gate.py`):
```python
def test_kill_ratio_below_threshold_red(self):
    rep = mutation_gate.summarize_mutmut_output(
        "5 mutants killed, 5 mutants survived")
    self.assertEqual(rep["kill_ratio"], 0.5)
    self.assertEqual(rep["verdict"], "red")  # < 0.8 default

def test_kill_ratio_above_threshold_green(self):
    rep = mutation_gate.summarize_mutmut_output(
        "9 mutants killed, 1 mutant survived")
    self.assertGreaterEqual(rep["kill_ratio"], 0.8)
    self.assertEqual(rep["verdict"], "green")
```

**GREEN outline:**
- `is_available()` checks mutmut import
- `summarize_mutmut_output(text)` — pure fn parsing `N killed, M survived` line
- `scan(target=Path)` runs `mutmut run --paths-to-mutate <target>`, then summarizes
- Reuses: `_envelope`, `subprocess.run`

**Commit:** `feat(mutation-gate): mutmut wrapper w/ graceful-skip (chunk 4 item A)`

#### item C4.B — assertion-density axis (YAML-decl)

**RED test** (`tests/test_assertion_density.py`):
```python
def test_test_method_no_assert_flagged(self):
    src = "class T:\n    def test_x(self): pass\n"
    findings = assertion_density.scan_text(src, path="bad.py")
    self.assertGreater(len(findings), 0)
```

**GREEN outline** (`skills/workflow/scripts/assertion_density.py`):
- AST visit ClassDef → FunctionDef nodes whose name starts with `test_`
- Walk body for `Call` nodes where `.func` resolves to `self.assert*`
- Flag test methods with zero matching assert calls
- Reuses: `_envelope`, stdlib `ast`

**Commit:** `feat(assertion-density): AST scan for assert-free test methods (chunk 4 item B)`

#### items C4.C / C4.D — parametrize-coverage + error-path-coverage

Same standalone-Python shape as C4.B (AST scans, `scan_text` pure-fn, `_envelope` emit). Each gets a paired test in `tests/test_<name>.py` and a bin symlink. NO dependency on axis_runner — these are classic Python axes; the MERGE step retrofits them to YAML if/when needed.

#### item C4.E — chunk close-out

**RED:** full suite `OK` with no failures.

**GREEN:**
1. Write `.chunks/4/perms.json` (8 entries — 4 script + 4 bin).
2. Write `.chunks/4/progress.md` (one arch row).
3. Write `.chunks/4/backlog.jsonl` with 4 BK-NNN entries: `{"title": "Retrofit <axis> to YAML axis_runner", "section": "parked", "verify": "axis_runner identifies same findings as legacy"}`.

**Commit:** `chore(chunk-4): close-out — 1 graceful-skip + 3 standalone AST axes + fragments`

### Done when:

- [ ] 1 graceful-skip wrapper + 3 standalone Python axes shipped
- [ ] All 4 paired tests green
- [ ] Full suite 0 regressions
- [ ] `.chunks/4/{perms,progress,backlog}.{json,md,jsonl}` all present
- [ ] **NO consumption of axis_runner** (chunk 4 stays independent of chunk 3)

### Dispatch (paste-ready)

```python
Agent(
    description="Coverage-axes chunk 4 — Test quality + mutation (standalone)",
    subagent_type="kaizen-implementer",
    isolation="worktree",
    prompt="""Implement Chunk 4. PARALLEL with chunks 1, 2, 3, 5. NO deps.

WORKING DIR: /home/cherry86/workspace/kaizen-md
READ:
1. docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-4
2. docs/superpowers/templates/chunk-plan-template.md (4-section shape + isolation contract)
3. plugins/kaizen/skills/workflow/scripts/dead_code.py (graceful-skip template)
4. plugins/kaizen/skills/workflow/scripts/class_name_quality.py (AST scan template)

SKILLS: kaizen:tdd, kaizen:plugin-development

ISOLATION CONTRACT (read carefully):
- DO NOT consume axis_runner from chunk 3 (build as standalone Python — keeps chunk 4 independent)
- NEVER write to plugin.json, progress.md, backlog.json — all fragments to .chunks/4/
- Only touch files in your Owns list

EXECUTE: C4.A → C4.E in order. RED → GREEN → commit per item.

BUDGET: ~70 tool calls."""
)
```

---

## Chunk 5: Cross-project audit using the 30 pre-existing axes (semantic-search only)

| field        | value                                                                                                |
|--------------|------------------------------------------------------------------------------------------------------|
| **Purpose**  | Run the 30 ALREADY-SHIPPED kaizen-* coverage axes (the ones in master before this plan started) against semantic-search, dump findings, file the top-N as semantic-search backlog, and wire 3 axes into semantic-search's `verify_cmd`. Stays scoped to pre-existing axes to remain independent of chunks 1-4. |
| **Project**  | `~/workspace/semantic-search` (write surface) + read-only refs to `~/workspace/kaizen-md`            |
| **Deps**     | —                                                                                                    |
| **Outputs**  | semantic-search-side: `.kaizen.toml` + `scripts/coverage-gate.sh` + `docs/2026-MM-DD-coverage-findings.md` + backlog items |
| **Subagent** | `general-purpose` (cross-repo)                                                                       |
| **Isolation**| none (different repo entirely — naturally isolated from chunks 1-4)                                  |
| **Budget**   | ~50 tool calls                                                                                       |

### Guide

- **Working dirs:** primary `~/workspace/semantic-search`; reference `~/workspace/kaizen-md`
- **Skills to load FIRST:** none specific (cross-project plumbing)
- **Files to read FIRST:**
  - `~/workspace/semantic-search/.kaizen.toml` — current state
  - `~/workspace/semantic-search/.kaizen/workflow/backlog.json` — existing backlog
  - `~/workspace/kaizen-md/docs/superpowers/plans/2026-05-18-coverage-loop-implemented.md` — the 30 axes inventory
- **Conventions:**
  - Don't modify semantic-search source files; only add gate config + findings docs
  - File backlog items via `kaizen backlog add --section next_up --ref <kaizen-md-axis-name>`
  - Commit messages in semantic-search reference kaizen-md plan path
- **Upstream decisions:**
  - `verify_cmd` in `.kaizen.toml` is the gate hook (per kaizen-md CLAUDE.md convention)
  - Pick 3 axes to gate-block (perm-coverage + bin-coverage + heavy-imports — high signal, low noise)
- **What NOT to touch:**
  - semantic-search source code (audit, don't fix from this chunk)
  - kaizen-md plugin (read-only here — different repo)
  - Any kaizen-md `.chunks/N/` fragment (chunks 1-4's outputs — not visible until MERGE)
  - Any axis newer than the 30 pre-existing (chunks 1-4 axes get wired in MERGE step's cross-pollination phase)

### Isolation contract

**Owns (exclusive write):**
- `~/workspace/semantic-search/.kaizen.toml` (single-file edit — no other chunk touches semantic-search)
- `~/workspace/semantic-search/scripts/coverage-gate.sh` (NEW)
- `~/workspace/semantic-search/docs/2026-MM-DD-coverage-findings.md` (NEW)
- `~/workspace/semantic-search/.kaizen/workflow/backlog.json` (via `kaizen backlog add` CLI only — never hand-edit the JSON)

**Reads only (NEVER writes):**
- `~/workspace/kaizen-md/` (entirely read-only — chunk 5 is a consumer of the already-shipped axes)
- ANY `~/workspace/kaizen-md/.chunks/N/` fragments (don't exist yet from chunk 5's POV)

**Cross-repo isolation:** chunk 5 runs in a completely different repo than chunks 1-4. There is no possible file collision. Chunk 5 does NOT need a `.chunks/5/` fragment dir on the kaizen-md side — it writes directly into semantic-search since the MERGE step doesn't need to consolidate semantic-search files (different repo, different gate).

**No worktree needed** — semantic-search is a separate repo; chunks 1-4's kaizen-md worktrees are invisible here.

### Task list (checklist)

- [ ] **C5.A** Verify kaizen plugin installed in semantic-search project root (bin/kaizen-* on $PATH)
- [ ] **C5.B** Run all 30 shipped axes against semantic-search; collect findings into one docs file
- [ ] **C5.C** File top-10 actionable findings as semantic-search backlog items
- [ ] **C5.D** Wire 3 axes (perm-coverage + bin-coverage + heavy-imports) into semantic-search verify_cmd
- [ ] **C5.E** chunk close-out — commit refs kaizen-md plan path

### Plan

| Action  | Path                                                                          | Responsibility                                  |
|---------|-------------------------------------------------------------------------------|-------------------------------------------------|
| Verify  | `~/workspace/semantic-search/` (no edit)                                      | bin/kaizen-* on PATH from semantic-search cwd   |
| Create  | `~/workspace/semantic-search/docs/2026-MM-DD-coverage-findings.md`            | per-axis findings rollup                        |
| Modify  | `~/workspace/semantic-search/.kaizen.toml`                                    | verify_cmd: `bash scripts/coverage-gate.sh`     |
| Create  | `~/workspace/semantic-search/scripts/coverage-gate.sh`                        | invokes 3 kaizen-* gates                        |
| Append  | `~/workspace/semantic-search/.kaizen/workflow/backlog.json` (via CLI)         | 10+ backlog items                               |

### TDD code chunks

#### item C5.A — install verification

**RED:** `cd ~/workspace/semantic-search && command -v kaizen-perm-coverage`

Expected: exits 0, prints path.

If not on PATH: `bash plugins/kaizen/skills/workflow/scripts/install.sh` from kaizen-md repo.

**Commit:** none (verification only)

#### item C5.B — run all 30 axes

**RED:** create the findings doc with stub sections; expected to be filled.

**GREEN outline (script):**
```bash
cd ~/workspace/semantic-search
for axis in perm-coverage hook-coverage bin-coverage ...; do
    echo "## $axis"
    kaizen-$axis report --json | jq -r '.data | tojson | tostring[0:500]'
    echo
done > docs/2026-MM-DD-coverage-findings.md
```

**Commit:** `docs(coverage): per-axis findings rollup from kaizen-md axes (chunk 5 item B)`

#### item C5.C — file backlog items

**GREEN:** for each high-priority finding:
```bash
kaizen backlog add \
    --title "Fix <finding>" \
    --probe "Surfaced by kaizen-<axis>: <details>" \
    --verify "kaizen-<axis> gaps exits 0" \
    --section next_up \
    --ref ~/workspace/kaizen-md/docs/superpowers/plans/2026-05-18-coverage-loop-implemented.md
```

**Commit:** `chore(backlog): file 10 coverage findings from kaizen audit (chunk 5 item C)`

#### item C5.D — wire 3 gates

**RED:** `cat .kaizen.toml | grep verify_cmd` shows it's empty.

**GREEN:**
- `scripts/coverage-gate.sh`:
  ```bash
  #!/bin/bash
  set -e
  kaizen-perm-coverage gaps --json | jq -e '.data.gaps == []' >/dev/null
  kaizen-bin-coverage  gaps --json | jq -e '.data.gaps == []' >/dev/null
  kaizen-heavy-imports gaps --json | jq -e '.data.findings == []' >/dev/null
  ```
- `.kaizen.toml`: `verify_cmd = "bash scripts/coverage-gate.sh"`

**Commit:** `feat(gate): wire 3 kaizen coverage gates into verify_cmd (chunk 5 item D)`

#### item C5.E — chunk close-out

**Commit:** `chore(progress): chunk 5 close-out — cross-repo wiring complete (Refs: ~/workspace/kaizen-md/docs/.../5-chunks.md::chunk-5)`

### Done when:

- [ ] `.kaizen.toml::verify_cmd` invokes the 3 gates
- [ ] `docs/2026-MM-DD-coverage-findings.md` lists per-axis findings
- [ ] ≥10 backlog items filed in semantic-search with `--ref` to kaizen-md plan
- [ ] All gate runs green when verified manually (`bash scripts/coverage-gate.sh`)

### Dispatch (paste-ready)

```python
Agent(
    description="Coverage-axes chunk 5 — Cross-project wiring into semantic-search",
    subagent_type="general-purpose",
    prompt="""Chunk 5 — parallel with chunk 4. Deps: chunk 3.

WORKING DIRS: primary /home/cherry86/workspace/semantic-search; ref /home/cherry86/workspace/kaizen-md

READ FIRST:
1. /home/cherry86/workspace/kaizen-md/docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-5
2. /home/cherry86/workspace/semantic-search/.kaizen.toml
3. /home/cherry86/workspace/semantic-search/.kaizen/workflow/backlog.json
4. /home/cherry86/workspace/kaizen-md/docs/superpowers/plans/2026-05-18-coverage-loop-implemented.md (the 30 axes inventory)

EXECUTE: Task list (checklist) C5.A → C5.E. Per-item RED → GREEN → commit (some items have no RED — verification only).

DON'T:
  - modify semantic-search source files (audit, don't fix)
  - modify kaizen-md (read-only here)

DONE WHEN: 3-gate verify_cmd wired, findings doc exists, ≥10 backlog items filed referencing kaizen-md plan.

BUDGET: ~50 tool calls."""
)
```

---

## MERGE step (RUN BY PARENT ORCHESTRATOR — never by chunk agents)

**Trigger:** all 5 chunks done (their per-chunk `Done when` gates clear AND their commits merged to master). Chunks 1-4 land via worktree-branch merges; chunk 5 is cross-repo so already committed in semantic-search.

**Inputs (from kaizen-md master post-merge):**
- `.chunks/1/perms.json`, `.chunks/1/progress.md`
- `.chunks/2/perms.json`, `.chunks/2/progress.md`
- `.chunks/3/perms.json`, `.chunks/3/progress.md`, `.chunks/3/backlog.jsonl`, `.chunks/3/mcp-mounts.txt`
- `.chunks/4/perms.json`, `.chunks/4/progress.md`, `.chunks/4/backlog.jsonl`

(Chunk 5 produces no fragments — its outputs land directly in semantic-search.)

**Actions (single sequential pass — no concurrency):**

1. **Consolidate plugin.json perms:**
   ```bash
   python3 -c "
   import json
   from pathlib import Path
   pj = Path('plugins/kaizen/.claude-plugin/plugin.json')
   raw = json.loads(pj.read_text())
   allow = list(raw['permissions']['allow'])
   for frag in sorted(Path('.chunks').glob('*/perms.json')):
       for entry in json.loads(frag.read_text()):
           if entry not in allow:
               allow.append(entry)
   raw['permissions']['allow'] = allow
   pj.write_text(json.dumps(raw, indent=2) + '\n')
   "
   ```

2. **Consolidate architecture log:**
   ```bash
   for frag in $(ls .chunks/*/progress.md | sort); do
       cat "$frag" >> .kaizen/workflow/progress.md
   done
   ```

3. **Consolidate backlog (chunks 3 + 4 only):**
   ```bash
   for frag in $(ls .chunks/*/backlog.jsonl 2>/dev/null | sort); do
       while IFS= read -r line; do
           [ -z "$line" ] && continue
           python3 -c "import json,subprocess,sys
   row = json.loads(sys.argv[1])
   subprocess.run(['kaizen', 'backlog', 'add',
       '--title', row['title'], '--probe', row.get('probe', ''),
       '--verify', row.get('verify', ''),
       '--section', row.get('section', 'parked'),
       '--ref', row.get('ref', ''), '--tags', row.get('tags', '')], check=True)" "$line"
       done < "$frag"
   done
   ```

4. **Wire MCP mounts (chunk 3):**
   - Read `.chunks/3/mcp-mounts.txt` (one tuple per line)
   - Edit `plugins/kaizen/skills/workflow/scripts/gateway.py::SUBSERVERS` to append each tuple
   - Single Edit call appending the lines inside the list literal

5. **Cross-pollinate axis_runner with chunks 1+2+4 outputs (the deferred retrofit):**
   - Now that axis_runner (chunk 3) AND all standalone axes (chunks 1, 2, 4) coexist, retrofit ≥5 simple AST/grep-shaped axes to YAML form
   - For each retrofitted axis: write `skills/<feature>/domain/axes/<name>.yaml`, re-target `bin/kaizen-<name>` to `axis_runner.py`, update paired test, delete the legacy `.py` (use `KAIZEN_ALLOW_DELETE=1` — authorized by plan)
   - Remaining axes stay as classic Python until a future retrofit sprint (already parked as `.chunks/3/backlog.jsonl` BK-NNN entries)

6. **Cross-pollinate semantic-search with chunks 1-4 new axes:**
   - Run each new axis (chunks 1-4) against semantic-search
   - Append findings to `~/workspace/semantic-search/docs/2026-MM-DD-coverage-findings.md` (the doc chunk 5 created)
   - File any high-signal findings as additional semantic-search backlog items

7. **Cleanup:** `rm -rf .chunks/` (fragments consolidated — no longer needed)

8. **Single merge commit:**
   ```
   chore(merge): consolidate chunks 1-5 fragments + retrofit + cross-pollination

   - plugin.json: +X perm entries
   - progress.md: +N arch rows
   - backlog: +M parked items
   - gateway.py: +1 mcp mount (axis_runner)
   - retrofitted 5 axes to YAML (chunks 1, 2, 4 outputs)
   - cross-pollinated chunks 1-4 axes into semantic-search findings

   Refs: docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md
   ```

9. **Final verification:**
   ```bash
   cd plugins/kaizen && python3 -m unittest discover -s tests -p "test_*.py" | tail -3
   bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh | tail -10
   ```
   Expected: 0 regressions on the post-MERGE state.

**Why this works (the isolation guarantee):**
- During chunks 1-4, no two agents ever write the same file (different script names, different test names, different bin names, different `.chunks/N/` fragment dirs)
- Chunk 5 is cross-repo, naturally invisible to chunks 1-4
- Shared files (`plugin.json`, `progress.md`, `backlog.json`, `gateway.py`) are write-protected for chunk agents — they only get touched by the parent during MERGE
- The MERGE step is single-writer by construction (parent orchestrator, sequential actions)
- If any chunk fails mid-flight, its worktree branch isn't merged and its `.chunks/N/` fragments are absent — MERGE simply skips them and proceeds with the others

## Plan-level done when

- [ ] All 5 chunks' per-chunk "Done when" gates cleared
- [ ] All 5 chunk branches merged to master in kaizen-md (chunks 1-4) + cross-repo commits in semantic-search (chunk 5)
- [ ] MERGE step's 9 actions all completed
- [ ] `.chunks/` directory deleted
- [ ] Final smoke: `bash plugins/kaizen/skills/workflow/scripts/test-pipeline.sh` green
- [ ] Master checklist updated: `2026-05-18-coverage-checklist.md` flips 10-15 more rows to `[x]`

## Cross-project hand-off note

If chunk 5 spawns a longer body of work in semantic-search, it itself becomes a parent plan in that repo using the same template. The "Source / brainstorm" field would then chain: `~/workspace/kaizen-md/docs/superpowers/plans/2026-05-18-coverage-axes-5-chunks.md::chunk-5`.
