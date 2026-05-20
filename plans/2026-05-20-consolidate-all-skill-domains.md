# Plan: consolidate all skill domain/ → schemas/<name>/

## Status

**IN-PROGRESS 2026-05-20** — apply the schemas/workflow/ consolidation
pattern across all 22 remaining skills with a `domain/` directory.

## Goal

Make `plugins/kaizen/schemas/` the single home for every yaml config +
JSON Schema in the plugin. After this plan:

- `skills/<X>/domain/` is gone for all skills
- `schemas/<X>/` holds the yaml configs + nested schemas/
- Production code finds schemas at the canonical location
- Collisions with existing routine schemas resolve via co-location
  (single dir per name, holds both routine `schema.yaml` AND skill
  domain yamls)

## Current state

22 skills with `domain/`:

| Skill | Files | Collision with routine schemas/? |
|---|---|---|
| agent-formatting | 2 | — |
| audit | 2 | **YES** (schemas/audit/schema.yaml exists) |
| auto-handoff | 6 | — |
| brain | 4 | — |
| brainstorming | 2 | — |
| chatlog | 2 | — |
| code-tour | 5 | — |
| decision-rubric | 1 | — |
| deus-ex-machina | 7 | — |
| efficient-tool-use | 2 | — |
| handoff | 12 | — |
| intent | 6 | — |
| iron-laws | 2 | — |
| karpathy | 2 | — |
| loop | 2 | — |
| memory-ledger | 1 | — |
| plugin-development | 6 | **YES** (schemas/plugin-development/schema.yaml) |
| plugin-self-audit | 4 | — |
| schema-driven-cli | 2 | — |
| self-improving | 2 | — |
| token-bloat | 2 | — |
| verify-before-execution | 1 | — |

Total: ~75 files to move + ~100 callers to update.

## Convention (post-consolidation)

```
schemas/<name>/
├── <main-config>.yaml             (or schema.yaml for routines)
├── <secondary-configs>.yaml       (when the skill has multiple)
├── axes/<X>.yaml                  (declarative axes — workflow's pattern)
└── schemas/<X>.schema.json        (JSON Schemas validating the yamls)
```

For collisions (`audit`, `plugin-development`): both the routine
`schema.yaml` and the skill's domain yamls live in the SAME dir.
Prefix the skill's domain files with the skill name when filenames
would otherwise be too generic to disambiguate (e.g.
`schemas/audit/audit-axes.yaml` rather than just `axes.yaml`). The
routine `schema.yaml` keeps its canonical name.

## Invariants

- Tests stay green at every commit (`kaizen-tests` after each skill)
- One commit per skill (bisect-friendly)
- Same `_kaizen_paths` / `_bootstrap` infra already in place — no new
  helpers needed
- Production code that READS a domain yaml gets its path updated to
  the canonical location
- Hooks/skills that don't read yaml directly are unaffected

## Phases

### Phase A — Small skills (1-2 files each, no collisions)

Skills that move trivially: agent-formatting, brainstorming, chatlog,
decision-rubric, efficient-tool-use, iron-laws, karpathy, loop,
memory-ledger, schema-driven-cli, self-improving, token-bloat,
verify-before-execution. (13 skills, ~17 files.)

For each:
1. `git mv skills/<X>/domain/* schemas/<X>/`
2. Grep + replace callers
3. `kaizen-tests --concurrency 4` → green
4. Commit `refactor(<X>): consolidate domain/ -> schemas/<X>/`

### Phase B — Medium skills (4-7 files, no collisions)

Skills: brain (4), plugin-self-audit (4), code-tour (5), intent (6),
auto-handoff (6), deus-ex-machina (7). (6 skills, ~32 files.)

Same per-skill workflow as Phase A.

### Phase C — Large skills (12 files, no collisions)

handoff (12 files). One commit.

### Phase D — Collision skills (co-locate)

audit + plugin-development. The skill's domain yamls join the existing
`schemas/<X>/schema.yaml`. Filenames preserved.

### Phase E — assets/schemas/ verdict

Decide whether assets/schemas/ (16 .schema.json files) moves under
schemas/, gets renamed, or stays. assets/ implies "loaded as data by
runtime code" (distinct from "validates a yaml in schemas/"). Decision
deferred to end of plan after the rest converges.

### Phase F — Cleanup + docs

- Update all SKILL.md files that mention `domain/`
- Update plugin-development SKILL.md's feature-shape guidance
- Update DEVOPS-CHEAT-SHEET.md
- Append progress.md row
- Run full `kaizen-tests` + `kaizen-health`

## Execution strategy

Dispatch 3-4 worktree-isolated subagents in parallel:
- Subagent 1: Phase A skills 1-5
- Subagent 2: Phase A skills 6-13
- Subagent 3: Phase B
- Subagent 4: Phase C + D + E (sequential since handoff is large + collisions need care)

Each subagent commits per-skill. Parent merges all branches back to
master after each subagent completes.

## Verification

```bash
# Per-skill regression check
kaizen-tests --concurrency 4

# Post-phase: zero stale refs
grep -rEln 'skills/[a-z-]+/domain' \
    --include='*.py' --include='*.sh' --include='*.json' --include='*.yaml' --include='*.md' \
    plugins/ scripts/ .github/ 2>/dev/null | \
    grep -v __pycache__ | grep -v CHANGELOG
# Expect: empty

# Final health
kaizen-health
bash plugins/kaizen/scripts/ops/test-pipeline.sh
```

## Rollback

Per-skill commits make every step revertable (`git revert <sha>`).
The aggregate plan-commit at the end can be reverted as a unit if the
suite regresses unexpectedly.

## Resume protocol

Read this plan's `## Phases` section; the last `- [x]` checkbox marks
the completed skill. The next skill in the table is the resume point.

## Out of scope

- assets/schemas/ → schemas/ migration (Phase E placeholder; decision
  deferred)
- Adding NEW JSON Schemas where none currently exist (would require
  schema authoring per consumer; separate task)
- Renaming any existing schema or yaml files
- Onion-DDD layout changes inside the skills themselves
