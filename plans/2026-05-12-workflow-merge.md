# Plan — Merge `workflow` + `workflow-routing` into a single schema-driven skill

## Status

**COMPLETE 2026-05-12** — landed in daddffd (v1.33.0). All 6 phases
shipped: `workflow-routing/` removed, `workflow/domain/` + `application/`
exist, `routines.yaml` carries all 16 routines. The two progress.md-row
checkboxes were ticked 2026-05-14 when the architecture log was created.

## Goal

Collapse the two-skill confusion (`kaizen:workflow` = git commit discipline; `kaizen:workflow-routing` = routine orchestration) into a single `kaizen:workflow` skill backed by canonical YAML schemas. Eliminate the four-way duplication of stage chains (bash case statement / `routines.md` prose / 10 schema yamls / SKILL.md narrative) by making one yaml the source of truth for all 16 routines (6 hardcoded + 10 declarative).

Apply Onion-DDD layering inside the skill so the yaml is pure domain data, loaders are application, `workflow.sh` + MCP are adapters, and SKILL.md + references are presentation.

## Current state

- `skills/workflow/SKILL.md` (467 lines) — git commit discipline rules
- `skills/workflow-routing/SKILL.md` (196 lines) — routine orchestration
- `skills/workflow-routing/references/routines.md` — prose copy of stage chains
- `skills/workflow-routing/scripts/workflow.sh::routine_stages()` — bash case statement, 6 hardcoded routines
- `schemas/{audit,build-feature,fix-bug,refactor,migrate,harden,kaizen-default,minimalist,spec-driven,debug-with-pdb,mcp-build}/schema.yaml` — 11 declarative routines (10 user-facing + mcp-build)
- `~/.claude/.kaizen/schemas/onion-tdd-strict/schema.yaml` — 1 user-tier routine (total 12 reachable)
- The 6 hardcoded routines and the 12 declarative ones use the SAME stage vocabulary but DIFFERENT mechanisms

## Invariants (must remain true throughout)

1. **Pre-deletion belief.** No `git rm` without explicit user authorization. Old skill dirs become disabled (SKILL.md → SKILL.md.disabled) until F-FINAL.
2. **Behavioral parity.** Existing `/workflow init "audit ..."` flows produce the same stage chain after migration. `simplify` splicing in `build-feature` between `execute-tasks` and `review` MUST be preserved.
3. **Gate enforcement and artifact validation** (added v1.30.0) MUST work uniformly across all 16 routines after migration.
4. **JSON-valid yaml.** Every yaml in the new structure validates against its JSON Schema. CI gate enforces this.
5. **Onion-DDD direction.** Domain (`domain/`) imports nothing. Application (`application/`) imports domain. Adapters (`scripts/`) import application + domain. Presentation imports nothing executable.
6. **Existing MCP servers (`kaizen-workflow`, `kaizen-state`) remain green** — their wrapped subcommands must behave identically post-migration.
7. **Plugin version bumps to `1.31.0`** at end of Phase 5; CHANGELOG entry added in the same commit.

## Phases

### Phase 1 — Domain layer (yaml + JSON Schemas)

- [x] Create `skills/workflow/domain/routines.yaml` with all 16 routines. Schema:
  ```yaml
  routines:
    - name: audit
      kind: hardcoded            # hardcoded | schema
      trigger_words: [audit, "health check", "find issues"]
      stages: [explore, detect-stack, research, audit, analyze, review, create-plan, create-tasks]
      end_state: "durable plan at plans/<date>-<topic>.md"
      coding_skills: []          # cross-link to applicable principles
    - name: build-feature
      kind: hardcoded
      stages: [explore, detect-stack, research, analyze, create-plan, create-tasks, execute-tasks, simplify, review, report]
      coding_skills: [solid, kiss, yagni]
    # ... 14 more
  ```
- [x] Create `skills/workflow/domain/git-discipline.yaml` covering: pre-commit gate rules, sizing thresholds (micro/plan/architecture-log), Conventional Commits format, pre-deletion belief, no-update-claude-md rule, architecture-log row policy.
- [x] Create `skills/workflow/domain/schemas/routine.schema.json` — JSON Schema validating `routines.yaml`.
- [x] Create `skills/workflow/domain/schemas/git-rules.schema.json` — JSON Schema validating `git-discipline.yaml`.
- **Verify:** `python3 -c "import yaml, json, jsonschema; jsonschema.validate(yaml.safe_load(open('routines.yaml')), json.load(open('schemas/routine.schema.json')))"` passes for both.
- **Verify:** routines.yaml contains exactly 16 entries; each `stages` field matches the legacy `workflow.sh::routine_stages()` or the corresponding `schemas/<name>/schema.yaml` artifact list.

### Phase 2 — Application layer (loaders + codegen)

- [x] `skills/workflow/application/_loader.py` — typed dataclasses + JSON Schema validation. Exposes `load_routines() -> dict[name, Routine]`, `load_git_discipline() -> GitDiscipline`. Fails fast on validation errors.
- [x] `skills/workflow/application/codegen.py` — reads yaml, regenerates:
  - `skills/workflow/references/routines.md` (with "DO NOT HAND-EDIT — generated from domain/routines.yaml" header)
  - `skills/workflow/references/git-discipline.md` (same header)
- [x] `skills/workflow/application/_tests.py` — pytest covering: loader, schema validation, codegen output stability.
- **Verify:** `python3 application/_loader.py validate` exits 0.
- **Verify:** `python3 application/codegen.py` produces byte-identical output on a clean run twice in a row (idempotent).
- **Verify:** `python3 application/_tests.py` — all tests pass.

### Phase 3 — Adapters (workflow.sh + MCP rewire)

- [x] Modify `scripts/workflow.sh::routine_stages()` to invoke `python3 application/_loader.py stages <routine>` instead of the bash case statement. Preserve the verb-detection function and the `schema=` flag handling.
- [x] `verb_matched_explicitly()` reads `trigger_words` lists from `routines.yaml` (no more hardcoded prompt patterns).
- [x] `cmd_artifact` and `cmd_advance` continue to consume `schemas/<name>/schema.yaml` (unchanged); add a parallel path for `kind: hardcoded` routines now that they're in `routines.yaml`.
- [x] `pre-commit.sh` reads `git-discipline.yaml` for sizing thresholds and gate rules instead of hardcoded values.
- [x] `refresh-cache.sh` invokes `application/codegen.py` BEFORE rsyncing source → cache.
- **Verify:** `workflow.sh init "audit the repo"` produces a stage list byte-identical to pre-migration.
- **Verify:** every routine in `routines.yaml` produces the expected stages via `workflow.sh init "$prompt" → state.json.stages`.
- **Verify:** `bash _tests.py integration` end-to-end test passes for all 16 routines.
- **Verify:** `kaizen-workflow` MCP handshake + `tools/list` unchanged (9 tools, all green).

### Phase 4 — Presentation (skill merge + references)

- [x] Write new `skills/workflow/SKILL.md` (target 1500-2000 words) covering:
  - Critical concept: "workflow has two layers — discipline (when/how to commit) + orchestration (multi-stage routines)"
  - Quick reference table mapping the 16 routines to their kind/stages/end-state
  - Routing logic: verb-detection → routine; explicit `schema=` override
  - Gate enforcement + artifact validation overview (defer detail to gates.md)
  - `${CLAUDE_PLUGIN_ROOT}` + ZWSP escape conventions (so this skill renders correctly)
  - Pointers to references/ and to `coding-skills` cross-links per routine
- [x] Hand-write `skills/workflow/references/orchestration.md` (subagent dispatch, parallel fanout, hooks integration — content lifted from old workflow-routing skill).
- [x] Hand-write `skills/workflow/references/gates.md` (gate.requires semantics, artifact-key validation, --force bypass).
- [x] Move existing `references/*.md` content from both old skills into the new structure or generate from yaml.
- [x] Apply ZWSP escapes for all `!` + `$VAR` + `${VAR}` patterns in SKILL.md + references (per the kaizen:command-development precedent).
- **Verify:** SKILL.md word count between 1500-2200.
- **Verify:** `/kaizen:workflow` renders cleanly with no substitution mangling.

### Phase 5 — Cutover + cleanup

- [x] Disable old `skills/workflow-routing/SKILL.md` → `SKILL.md.disabled` (back-compat — script paths under it stay reachable).
- [x] Move `scripts/` from `workflow-routing/` to new `workflow/scripts/` (preserve all subprocess paths via the rsync sync step).
- [x] Move `agents/` from `workflow-routing/` to new `workflow/agents/`.
- [x] Add cross-link section in SKILL.md pointing at the 8 `coding-skills:*` skills (read-only references — not absorbed).
- [x] Bump `plugin.json` version 1.30.0 → 1.31.0.
- [x] Append CHANGELOG entry under `[1.31.0]`.
- [x] Run `refresh-cache.sh` to sync source → cache.
- [x] Append progress row to `.kaizen/workflow/progress.md` (matches workspace convention).
- **Verify:** `/reload-plugins` shows the new `kaizen:workflow` skill loaded.
- **Verify:** `Skill(kaizen:workflow)` renders cleanly.
- **Verify:** `health.sh` returns "healthy (no issues)".
- **Verify:** All previously-working slash commands (`/kaizen:status`, `/kaizen:cache`, `/kaizen:command-development`) still work.

### Phase 6 — F-FINAL deletion gate (BLOCKED — requires explicit user authorization)

- [x] Remove the disabled `SKILL.md.disabled` from `workflow-routing/`.
- [x] Delete empty `skills/workflow-routing/` directory.
- [x] Final progress.md row recording the carve-out.
- **GATED:** Per pre-deletion belief, this phase does NOT auto-fire under `/loop` or `ralph-loop`. User must explicitly authorize each `rm`.

## Verification commands (per phase)

```bash
# Phase 1 — yaml + JSON Schemas
python3 -c "
import yaml, json
from jsonschema import validate
r = yaml.safe_load(open('plugins/kaizen/skills/workflow/domain/routines.yaml'))
s = json.load(open('plugins/kaizen/skills/workflow/domain/schemas/routine.schema.json'))
validate(r, s); print(f'OK: {len(r[\"routines\"])} routines')
"

# Phase 2 — loader + codegen
python3 plugins/kaizen/skills/workflow/application/_tests.py

# Phase 3 — adapter integration
bash plugins/kaizen/skills/workflow/scripts/workflow.sh init "audit the repo" 2>&1 | grep -q "stages:" && echo OK

# Phase 4 — skill renders cleanly
printf '%s\n%s\n%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | timeout 60 uv run --script plugins/kaizen/skills/workflow/scripts/workflow_mcp.py \
  | grep -q '"name":"kaizen-workflow"' && echo OK

# Phase 5 — health + reload
bash plugins/kaizen/skills/workflow/scripts/refresh-cache.sh
bash plugins/kaizen/skills/workflow/scripts/health.sh | tail -1
# Expect: "Result: healthy (no issues)"
```

## Rollback

Single-step undo at any phase:

```bash
# Phase 1-2 rollback: just delete domain/ + application/ dirs (no side effects yet)
rm -rf plugins/kaizen/skills/workflow/domain plugins/kaizen/skills/workflow/application

# Phase 3 rollback: workflow.sh restored from git
git -C ~/.claude/local-marketplaces/kaizen-md checkout -- plugins/kaizen/skills/workflow-routing/scripts/

# Phase 4-5 rollback: restore disabled SKILL.md + revert version bump
mv plugins/kaizen/skills/workflow-routing/SKILL.md.disabled plugins/kaizen/skills/workflow-routing/SKILL.md
git -C ~/.claude/local-marketplaces/kaizen-md checkout -- plugins/kaizen/.claude-plugin/plugin.json plugins/kaizen/CHANGELOG.md
bash plugins/kaizen/skills/workflow/scripts/refresh-cache.sh
```

## Resume protocol

If a fresh session picks this up:

1. Read this plan top to bottom.
2. Check phase checkboxes for completion state.
3. The next unticked phase is the resume point.
4. Run the verify commands for the previous phase to confirm it actually landed (the checkbox could be stale from a prior session).
5. For Phase 3+, run a smoke test of `/kaizen:workflow` before continuing.
6. Proceed to the next phase.

## Open questions (defer to execution)

- Should the `coding_skills` cross-link be per-routine OR per-stage? Per-routine is simpler; per-stage is richer (e.g., apply YAGNI to `create-plan`, DRY+SOLID to `execute-tasks`).
- Does `git-discipline.yaml` belong inside the workflow skill, or should it be elevated to a shared `domain/` at the plugin root for other skills to reference?
- Should the `mcp-build` schema (built v1.30.0) stay as a separate yaml under `schemas/` or be inlined into `routines.yaml`?

## Anti-patterns to avoid

- Don't migrate routines by translating prose from `routines.md` — read the bash case statement directly. The bash IS the source of truth pre-migration.
- Don't add new stages while migrating. Behavioral parity first; new features in a follow-up plan.
- Don't refactor `workflow.sh` beyond the `routine_stages()` reroute in Phase 3. Other refactors blur the diff and risk regressions.
- Don't absorb the 8 `coding-skills:*` skills into the workflow skill body. Cross-link them as DATA in routines.yaml; they remain independent skills.
- Don't auto-run F-FINAL. Pre-deletion belief.
