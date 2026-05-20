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

- [ ] Run `kaizen-tests` to establish baseline (must be green)
- [ ] Build canonical→cluster map: for each shim basename, extract canonical
      cluster from its `MIGRATION BRIDGE — X moved to scripts/<cluster>/X.py`
      docstring; write to `/tmp/shim-map.json`
- [ ] Write `plugins/kaizen/tests/_kaizen_paths.py` — adds every
      `plugins/kaizen/scripts/<cluster>/` dir to `sys.path` on import.
      Tests `import _kaizen_paths` once instead of hand-rolling sys.path inserts.
- [ ] Single-test smoke: pick one test, replace its sys.path.insert with the
      helper, run it in isolation to confirm canonical resolution.

**Commit:** `chore(tests): add _kaizen_paths helper for canonical scripts/<cluster>/ resolution`

### Phase 2 — Migrate 89 test files to the helper

- [ ] For each test file: replace
      `sys.path.insert(0, str(<X> / "skills/workflow/scripts"))`
      with `import _kaizen_paths  # noqa: F401  -- adds scripts/<cluster>/ to sys.path`
- [ ] Run `kaizen-tests` after each batch of 20 files; bisect if any regress
- [ ] Verify: `grep -r 'skills/workflow/scripts' plugins/kaizen/tests/` returns 0

**Commits:** 4-5 batches, one per ~20 test files. Subject `refactor(tests): migrate <N> tests off shim sys.path (Wave <X>)`

### Phase 3 — Migrate 3 bash hooks

- [ ] `hooks/claude/sessionend-token-bloat.sh` →
      `$PLUGIN_ROOT/scripts/index/token_bloat.py` (or wherever token_bloat lives)
- [ ] `hooks/claude/auto-handoff.sh` →
      `$PLUGIN_ROOT/scripts/handoff/auto_handoff.py`
- [ ] `hooks/claude/session-start-token-bloat.sh` →
      same as the first one
- [ ] Smoke: fire each hook manually with a minimal event JSON

**Commit:** `fix(hooks): point 3 hooks at canonical scripts/<cluster>/ paths`

### Phase 4 — Verify zero callers + full test suite

- [ ] `grep -rEn 'skills/workflow/(scripts|application)/[a-zA-Z_]+\.py' \
        --include='*.py' --include='*.sh' \
        plugins/ scripts/ .github/ 2>/dev/null | \
        grep -v __pycache__ | grep -v CHANGELOG | grep -v 'plugins/kaizen/skills/workflow/'`
      → expect 0 hits (excluding the shims themselves + CHANGELOG history)
- [ ] `kaizen-tests` → all green
- [ ] `kaizen-health` → 0 errors
- [ ] `bash plugins/kaizen/scripts/ops/test-pipeline.sh` → TAP green
- [ ] `kaizen-gatekeeper check --staged` → no new findings

### Phase 5 — Sweep shims via kaizen-shim F-FINAL

- [ ] `kaizen-shim init workflow-shim-sweep` — create the deletion manifest
- [ ] Programmatically populate the manifest with all 116 shim paths
      (each entry: `<old-path> → DELETE` since canonical already exists)
- [ ] `kaizen-shim list --slug workflow-shim-sweep` — verify manifest = 116 entries
- [ ] `kaizen-shim sweep --slug workflow-shim-sweep --dry-run` — preview
- [ ] **USER GATE:** confirm the deletion list with the user (pre-deletion belief)
- [ ] `kaizen-shim sweep --slug workflow-shim-sweep --allow-delete` — F-FINAL
- [ ] `kaizen-tests` post-sweep — confirm green (helper resolves everything)

**Commit:** auto-generated by `kaizen-shim sweep`; one revertible commit with `git rm` of 116 files

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
