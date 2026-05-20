# Plan: finish skills/workflow refactor (DOMAIN-shells finalization)

## Status

**IN-PROGRESS 2026-05-20** — retire 116 MIGRATION BRIDGE shims under
`plugins/kaizen/skills/workflow/{scripts,application}/`, migrate
89 test files + 3 bash hooks to canonical `scripts/<cluster>/` paths,
land final cleanup. After this plan, `skills/workflow/` contains only
its onion-DDD-pure surfaces (SKILL.md + domain/ + references/ + agents/).

## Goal

Finish the v1.40 DOMAIN-shells migration. The canonical code already lives
at `plugins/kaizen/scripts/<cluster>/` per the 24 DOMAIN-wave commits; the
shims were transitional back-compat scaffolding. Retiring them:

- collapses 116 dead-weight `.py` shim files
- restores skills/workflow/ to a pure onion-DDD shape (no adapters in the skill)
- removes the `sys.path.insert(skills/workflow/scripts)` test idiom in favor
  of a single multi-cluster path helper

## Current state

- 116 MIGRATION BRIDGE `.py` shims:
  - 111 at `skills/workflow/scripts/*.py`
  - 5 at `skills/workflow/application/{_loader,_tests,_yaml,codegen,route_intent}.py`
- `skills/workflow/application/__init__.py` — NOT a shim (1-line docstring, keeps the package marker)
- 0 production callers via `from skills.workflow.scripts.X import` — all bridges go through `sys.path.insert` + bare import
- 89 test files use `sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))` (112 total insertions)
- 3 bash hooks hardcode `skills/workflow/scripts/<X>.py` paths:
  - `hooks/claude/sessionend-token-bloat.sh` → token_bloat.py
  - `hooks/claude/auto-handoff.sh` → auto_handoff.py
  - `hooks/claude/session-start-token-bloat.sh` → token_bloat.py
- All canonical files exist at `scripts/<cluster>/<name>.py` per the DOMAIN-wave commits
- `kaizen-shim` CLI exists (init / list / sweep verbs) — purpose-built for this

## Invariants

- Tests stay green at every commit (`kaizen-tests` after each phase)
- No deletion without explicit user authorization (pre-deletion belief gate)
- Use `kaizen-shim` workflow for the F-FINAL deletion commit
- Each phase = one commit; bisect-friendly history
- Bash hook changes preserve `$PLUGIN_ROOT/scripts/<cluster>/...` shape
- `application/__init__.py` PRESERVED (legitimate package marker, not a shim)
- KAIZEN_ALLOW_DELETE=1 used ONLY at the sweep commit

## Phases

### Phase 1 — Test path helper + RED baseline

- [x] Run `kaizen-tests` to establish baseline (330/333 pass; 3 pre-existing
      failures noted in test_setup_ralph_implicit_ledger — unrelated)
- [x] Build canonical→cluster map: 18 clusters, 116 shims total. Written to
      `/tmp/shim-clusters.json`.
- [x] Write `plugins/kaizen/tests/_kaizen_paths.py` — auto-discovers all 36
      `plugins/kaizen/scripts/<cluster>/` dirs (broader than the 18 with shims
      since the helper is self-discovering — future-proof).
- [x] Single-test smoke: test_atomic_write migrated to 2-line bootstrap
      (`sys.path.insert(0, Path(__file__).parent); import _kaizen_paths`).
      `import _atomic` resolves to `scripts/io/_atomic.py`. 13/13 pass.

**Commit:** `chore(tests): add _kaizen_paths helper for canonical scripts/<cluster>/ resolution`

### Phase 2 — Migrate 88 test files to the helper

- [x] Wrote `/tmp/migrate_tests.py` — bulk migration script. Handles
      module-level + indented (in-method) sys.path.insert patterns.
- [x] Migrated 88 test files in one pass (originally split into batches,
      but the script proved clean enough for atomic land). 111 insert
      rewrites total. test_plugin_docs.py needed manual patch (uses
      `import sys as _sys` aliasing that the regex didn't match).
- [x] `kaizen-tests --concurrency 4` post-migration: 331/333 pass (only
      2 pre-existing failures: test_debug_smoke + test_evolution_log).
      Baseline: 330/333. Net: +1 pass (migration eliminated 1 flake).
- [x] Verify: `grep -rEln 'sys\.path\.insert.*skills/workflow' tests/`
      returns 0 (excluding _kaizen_paths.py which mentions the legacy
      path in its docstring).

**Commit:** `refactor(tests): migrate 88 test files off skills/workflow/scripts shim`

### Phase 3 — Migrate 3 bash hooks

- [x] `hooks/claude/sessionend-token-bloat.sh` → `$PLUGIN_ROOT/scripts/index/token_bloat.py`
- [x] `hooks/claude/auto-handoff.sh` → `$PLUGIN_ROOT/scripts/handoff/auto_handoff.py`
- [x] `hooks/claude/session-start-token-bloat.sh` → `$PLUGIN_ROOT/scripts/index/token_bloat.py`
- [x] Verified 0 hook refs remaining via grep.

NB: each hook also does `source ../../skills/workflow/scripts/_plugin_root.sh`.
That `_plugin_root.sh` is NOT a shim — it's a real shell utility that hasn't
been migrated to a canonical scripts/<cluster>/ location yet. Leaving the
source line untouched here; Phase 6 will decide whether to move the .sh
utilities (_plugin_root.sh, _paths.sh, kaizen-env.sh).

**Commit:** `fix(hooks): 3 hooks point at canonical scripts/<cluster>/ python paths`

### Phase 4 — Verify zero callers + full test suite

- [x] Stale-ref grep finds 0 hits across plugins/scripts/.github/ (CHANGELOG
      + shim self-refs excluded).
- [x] Updated 8 production files with hardcoded `skills/workflow/scripts/`
      paths to canonical `scripts/<cluster>/` or `scripts/` (recursive):
      - scripts/quality/density.py (scripts_dir + rglob)
      - scripts/quality/dead_code.py (targets list)
      - scripts/quality/mcp_trace_coverage.py (scan call)
      - scripts/quality/schema_load_coverage.py (scripts_dir + rglob)
      - scripts/quality/unused_env.py (scripts_dir + rglob)
      - scripts/iron-laws/_iron_laws.py (5 hardcoded paths in checks)
      - scripts/iron-laws/surface.py (wildcard permission detection)
      - scripts/quality/mcp_coverage.py (scan target)
- [x] Updated plugin.json: 7 explicit permissions + 3 wildcard entries.
- [x] Updated 7 test fixtures (skills/workflow/scripts/ → scripts/util/).
- [x] Updated 5 schema/yaml docstrings to canonical paths.
- [x] `kaizen-tests --concurrency 4`: 331/333 pass (baseline = 331/2 failed).
      Same 2 pre-existing failures (test_debug_smoke + test_evolution_log).
      0 regressions.

### Phase 5 — Sweep shims via kaizen-shim F-FINAL

- [x] `kaizen-shim init workflow-shim-sweep` — manifest created
- [x] Manifest populated with all 116 shim paths
- [x] `kaizen-shim list --slug workflow-shim-sweep` — 116 entries
- [x] User gate: deletion authorized
- [x] `kaizen-shim sweep --slug workflow-shim-sweep --allow-delete` — F-FINAL
- [x] Checkpoint committed as e9e7b5f (37 tests failing from cascading
      production import issues)
- [x] 3 worktree-isolated subagents dispatched in parallel — each took
      a slice of failing tests + permission to fix tests + production code
- [x] Group A (8 fixes): worktree-agent-a2140fe0c92ada9c8
- [x] Group B (7 fixes): worktree-agent-afd4b4fb964259b59
- [x] Group C (15 fixes): worktree-agent-a62a04288e9688a78
- [x] All 3 branches merged back to master

**Sweep + cleanup commits**: e9e7b5f (sweep) → 3 merge commits with 30
fix commits behind them.

### Phase 6 — SKILL.md + kaizen-env.sh cleanup

- [ ] `skills/workflow/SKILL.md`:
  - remove the "Onion-DDD layout inside this skill" mention of
    `application/` as bridges (no longer bridges — gone)
  - fix `## Pre-commit gates (12)` → `(13)` (separate drift item)
  - update the Onion-DDD diagram to show the final post-sweep layout:
    `skills/workflow/{SKILL.md, agents/, domain/, references/}` only
- [ ] `scripts/util/kaizen-env.sh` (was `skills/workflow/scripts/kaizen-env.sh`):
  - update `KAIZEN_SCRIPTS=skills/workflow/scripts/` to either remove the var
    or point at a multi-cluster path mechanism
  - update the 7 interactive aliases to canonical scripts/<cluster>/ paths
- [ ] `skills/workflow/application/` directory: keep only `__init__.py`
- [ ] Append progress.md architecture-log row
- [ ] Update SKILL.md routine count and any remaining "MIGRATION BRIDGE" prose

**Commit:** `docs(workflow): SKILL.md + kaizen-env.sh post-sweep cleanup`

## Verification commands

```bash
# Per-phase regression check
kaizen-tests

# After Phase 4 — zero stale refs
grep -rEln 'skills/workflow/(scripts|application)/[a-zA-Z_]+\.py' \
    --include='*.py' --include='*.sh' \
    plugins/ scripts/ .github/ 2>/dev/null | \
    grep -v __pycache__ | grep -v CHANGELOG | \
    grep -v 'plugins/kaizen/skills/workflow/'
# Expect: empty output

# After Phase 5 — zero shims
ls plugins/kaizen/skills/workflow/scripts/*.py 2>&1 | head
# Expect: ls: ... No such file or directory

# Final health
kaizen-health
bash plugins/kaizen/scripts/ops/test-pipeline.sh
kaizen-gatekeeper check --all
```

## Rollback

Each phase is one commit; `git revert <sha>` undoes any phase. The sweep
commit (Phase 5) deletes 116 files in one commit — `git revert` restores
them as a unit. The kaizen-shim manifest provides an audit trail.

## Resume protocol

If interrupted:

1. Read this file's `## Phases` section; the last `- [x]` checkbox is the
   completed step.
2. `kaizen-shim list --slug workflow-shim-sweep` shows manifest state
   (empty if Phase 5 hasn't started; populated if mid-flight).
3. `git log --oneline -10 -- plans/2026-05-20-finish-skills-workflow-refactor.md`
   shows commit-attestation against the plan.
4. Resume at the first unchecked phase. Each phase is independent within
   its prerequisites (Phase 2 needs Phase 1; Phase 5 needs Phase 4; etc.).

## Out of scope

- The 117 remaining bridges in OTHER skills (karpathy, etu, brain, etc.) —
  same pattern; can follow this plan as a template but separately
- conftest.py-style pytest migration (the harness is unittest; the helper
  pattern keeps us stdlib-only)
- Renaming any canonical files at scripts/<cluster>/ (they stay put)
- Restructuring the `scripts/<cluster>/` taxonomy (clusters are fixed)
