# Kit-wide disciplines (SSOT)

> Single source of truth for every discipline that applies across the parallel-branches kit. Every doc in this folder must honor these. When you find a violation, fix it inline (Boy-Scout) and reference this file.

## D1 — All information must be explicit, never implied

Every value / threshold / path / decision / dependency / assumption MUST be written out as a concrete literal in the artifact. Never lean on:

- "the operator knows what we mean"
- "the agent will figure out reasonable defaults"
- "downstream phase will fill in details"
- "obvious from context"
- "we always do it this way"

These create implicit knowledge that survives only in the parent's session memory. **A subagent picking up the artifact fresh (worktree dispatch, queue-picker pick, handoff resume) cannot see implicit knowledge** — they guess wrong OR back-and-forth via help requests.

**Anti-test:** if a fresh subagent reading ONLY the artifact (no parent context) would have to guess at any value, the artifact has implicit information and is broken.

**Boy-Scout corollary:** when you answer an implicit-knowledge question during any kit phase, write the answer into the artifact inline before proceeding.

Source: `plugins/kaizen/skills/brainstorming/SKILL.md::UPGRADE NOTE`. This rule originates in brainstorming (earliest phase) and propagates downstream — a spec with implicit knowledge pollutes the plan; a plan with implicit knowledge pollutes the chunks; a chunk with implicit knowledge burns dispatch tokens on back-and-forth.

## D2 — Chunking floor: 2-3 items per subagent

**Decompose only when forced.** Below floor = setup waste (full setup paid for half the work). Above floor = cap breach + handoff complexity.

Routing tree (from `CHUNKING_FLOOR.md`):

```
N items
  ├── 1-3 items     → Tier 0: PARENT does it (NO subagent dispatch)
  ├── 4-6 items     → Tier 1: ONE subagent (no chunking)
  ├── 7-30 items    → Tier 2: CHUNKED at ceil(N/3) chunks
  └── 30+ items     → Tier 3: POOL — queue-picker with N workers
```

Floor is shape-invariant — applies to chunk-based AND queue-picker AND worker-pool equally. The shape determines routing; the floor determines per-agent size.

**Validator enforcement** (`_plan_check.py`): warn on any chunk with < 2 items unless `design_heavy: true` flag is set.

## D3 — Work-order size limits (line-based, not token-based)

Token budgets were too abstract and varied by content density. Replaced with line counts on the AUTHORED work-order file (`chunk-NN.yaml` or `item-NNN.yaml`):

| Measure                            | Default | Hard cap | Rationale                                                    |
|------------------------------------|---------|----------|--------------------------------------------------------------|
| **Lines per work-order YAML**      | ≤150    | ≤200     | Fits 2-3 items at floor with TDD snippets (~45 lines/item)  |
| **Items per chunk/item-batch**     | 2-3     | ≤3       | The floor (D2)                                               |
| **Lines per individual item entry**| ≤80     | ≤120     | RED snippet + GREEN outline + commit message; bigger = split |

Validator warns when:
- Chunk file > 200 lines (likely too many items)
- Single item entry > 120 lines (likely too big — split or move to `chunks/` design-heavy)

**This replaces all `budget_tokens` fields** in schemas, rubric, plan/chunk YAMLs. Line counts are concrete + measurable + don't vary by content density the way tokens do.

## D4 — Parallel-safe by construction

(From the architecture invariant.) No two agents ever write the same canonical file. Shared concerns (`plugin.json`, `progress.md`, `backlog.json`, `gateway.py::SUBSERVERS`) are write-protected for chunk agents and consolidated only by the MERGE step (parent-only, single writer).

Per-chunk owns disjoint paths; shared writes go to `.chunks/N/` fragment dirs.

## D5 — Merge is single-writer + always last

(From the architecture invariant.) Run only by the parent orchestrator after all chunks finish. Never by a chunk agent. Two stages: `interwave` (consolidate + render checklist) + `final` (retrofit + cross-pollinate + cleanup + commit + verify).

## D6 — Conflict pre-flight is non-negotiable

`kaizen-plan check` runs before every dispatch and merge. Catches:
- Cross-chunk ownership collisions (two chunks owning the same path)
- Duplicate worktree branches
- Duplicate fragment directories
- Cycles in `deps:`
- Refs to non-existent chunk IDs
- Sub-floor chunks (< 2 items unless design_heavy)
- Over-cap chunk files (> 200 lines)

Pre-flight failure = silent collision later = the worst failure mode. Always run.

## D7 — Schema-validated end-to-end

Every artifact in the kit must pass jsonschema validation before dispatch:
- `plan.yaml` against `master-plan.schema.json`
- `chunks/*.yaml` against `chunk.schema.json`
- `merge.yaml` against `master-plan.schema.json#/$defs/merge`
- Fragment files against their respective schemas at write time AND read time
- Ledger rows against `chunk-ledger.schema.json` per append

Schema-valid YAML is the only YAML that gets dispatched. No exceptions.

## D8 — KISS over capability

When two designs solve the same problem, pick the one with fewer moving parts. From this kit:

- Filesystem `os.rename` for atomic claim, NOT SQLite or fcntl locks
- Parent-as-xargs queue picker, NOT worker-self-picking atomic-rename pool
- Append-only JSONL for ledgers, NOT structured DB
- Markdown for CHECKLIST.md, NOT custom dashboard format
- Single `kaizen-plan` CLI, NOT 6 separate top-level bins

## D9 — YAGNI over speculation

Defer building until value is proven. From this kit:

- Chunk-library / `$template` indirection → defer until ≥3 plans demand it
- Live web dashboard → defer until operators ask for it
- CRDT shared state → never (filesystem suffices at our scale)
- Worker-pool atomic-rename → superseded by simpler queue picker before any implementation

## D10 — Boy-Scout — leave cleaner than found

When editing any kit doc, also fix any discipline violations encountered. Don't leave them for later; they decay into design debt.

---

## How each doc references this file

Every other doc in `docs/superpowers/templates/parallel-branches/` should have a header note:

```markdown
> **Disciplines:** all rules in `DISCIPLINES.md` apply. See D1 (explicit info), D2 (floor), D3 (line caps) especially.
```

Don't restate disciplines in each doc — that creates DRY-violating drift. Reference + read.
