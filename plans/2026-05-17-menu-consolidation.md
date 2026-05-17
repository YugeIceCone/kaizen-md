# Plan — menu consolidation across setup / workflow / loop

**Status:** drafting
**Authored:** 2026-05-17
**Author:** kaizen plugin development session
**Sources of truth:** plan, this file; progress, `.kaizen/workflow/progress.md`

## Goal

Consolidate the kaizen plugin's 58 slash commands + 74 bins + 35 hooks
into a coherent **menu surface** anchored on three entry points:

1. **`/kaizen:setup`** — the **super-menu** for "init defaults +
   extras". First-time install + ongoing reconfiguration.
2. **`/kaizen:workflow`** — configures **how Claude acts in this
   session**. Default scope: project; opt-in global. Inherits
   session-mode disciplines.
3. **`/kaizen:loop`** — the **bridge** into workflow, selectable
   while configuring workflow (ralph-loop pattern).

Each menu is a multiSelect-friendly AskUserQuestion picker following
the patterns proven in commits `be7638b` (setup menu) + `7ee8679`
(audit:axis multi-pick).

## Inventory (grounded — Phase 1)

| Surface | Count |
|---|---|
| Commands (incl. nested) | 58 |
| Bins | 74 (41 orphan — no slash) |
| Hooks | 35 |
| Skills | 91 |
| Agents | 7 |
| MCP servers | 25 |
| Workflow schemas | 13 (audit / debug-with-pdb / fix-bug / harden /
   kaizen-default / mcp-build / migrate / minimalist /
   plugin-development / ralph-loop / refactor / shim-and-sweep /
   spec-driven) |
| Scripts | 150 |

### 9-cluster cluster taxonomy (existing, in CLAUDE.md)

audit/quality (12) · observability (7) · brain/memory (3) · workflow
(8) · plugin-meta (14) · discovery/search (8) · dev-aids (6) ·
intent/session · writing/io

## Analysis (Phase 2)

### Real overlap

| Pair | Overlap | Resolution |
|---|---|---|
| `/kaizen:loop` ↔ `schemas/ralph-loop/` | Same ralph-loop machinery, two entry points (standalone slash + workflow routine) | Fold: `/kaizen:loop` becomes a thin alias to `/workflow schema=ralph-loop`. Or invert: `/kaizen:workflow` learns a `loop` sub-mode that walks the ralph schema. |
| `/kaizen:flow` ↔ `flow.py` AsyncNode primitive | Demo command for the runtime, not a user-facing workflow entry | Keep distinct (proven docs in CLAUDE.md); don't fold. |
| `/kaizen:setup` ↔ `/kaizen:bootstrap` ↔ `/kaizen:update` ↔ `/kaizen:refresh-cache` | 4 lifecycle commands; bootstrap warms uv-venvs (setup-adjacent), update pulls + reload (post-install), refresh-cache forces CC plugin cache | **setup becomes super-menu** that can dispatch to any of these as sub-flows. The 3 sibling commands stay as direct aliases (back-compat). |

### Loop ↔ workflow overlap (the user's specific call-out)

- `/kaizen:loop` = ralph-loop pattern (iterate-until-converged)
- `/kaizen:workflow` (no slash command today; uses /workflow from the
  external workflow plugin) drives `schemas/ralph-loop/schema.yaml`
  + 12 other routines
- **Decision (per user):** loop = bridge selectable WHILE configuring
  workflow. Workflow Q3 "run-mode" includes `loop` as one option.

### Workflow scope (per user)

- **Default**: project (`<repo>/.kaizen/workflow.json` for the active
  routine + mode + bundles)
- **Opt-in global**: `~/.claude/.kaizen/workflow-global.json`
- Precedence: project wins when both present; setup menu Q controls
  which one to write to.

## The proposed menu structure (Phase 3 brainstorm output)

Each category gets a multiSelect AskUserQuestion checklist. Total: **6
categories**, each is one slash command (or nested under existing).

### Category 1: Setup (super-menu)

`/kaizen:setup` (already partially shipped in `be7638b` — extend it)

```
Q1 [single]:  "What do you want?"
  - Default install (1-click, sensible defaults — detect-stack drives)
  - Custom install (drops into Q2-Q4 wizard)
  - Reconfigure (existing install — adjust scope / add-ons)
  - Uninstall
  - Health check only (read-only)
  - Maintenance (cache stats / update / refresh-cache)

(if Custom): Q2-Q4 from be7638b stay as-is (scope / add-ons / dry-run)
(if Default): detect-stack output picks sensible defaults; user confirms
(if Maintenance): Q-sub picks the maintenance verb (multiSelect)
```

**Defaults the "default install" picks based on detect-stack:**

| Detected | Default add-ons enabled |
|---|---|
| Rust | semantic-indexes (rust-analyzer is heavy enough to pair) |
| Python | semantic-indexes |
| Node/TS | (none — npm test fast enough on its own) |
| Monorepo (`workspace.is_workspace=true`) | --enable-all + browser |
| Dockerfile present | + auto-daemon (worth scheduling hygiene) |

### Category 2: Workflow (the "how Claude acts" config)

`/kaizen:workflow` — **new** slash command (not currently in
kaizen's namespace; the top-level `/workflow` is the external plugin).
**Note**: existing `/workflow` skill stays; kaizen wraps it with
its own QA.

```
Q1 [single]:  "Scope?"
  - Project only (recommended — writes <repo>/.kaizen/workflow.json)
  - Global only (writes ~/.claude/.kaizen/workflow-global.json)
  - Both (project overrides, global is the fallback)

Q2 [single]:  "Run-mode?"  ← THIS IS THE LOOP BRIDGE
  - One-shot routine (pick a schema; runs once)
  - Loop (ralph-loop iteration until convergence)
  - Neither (just persist disciplines, don't start anything)

Q3 [multiSelect]:  "Disciplines (coding-style + operational + work-mode bundles)"
  - Inherit from /kaizen:session-mode (if set)
  - Override: Simplicity / Structure / Process / Karpathy
  - Override: Quality / Security / Brain-hygiene / Plugin-dev
  - Override: Discovery / Debugging / Refactoring / Planning

Q4 [single]:  "Auto-handoff threshold"
  - 25% / 50% / 75% / 85% / Disabled
```

### Category 3: Loop (the bridge, accessed via workflow Q2)

When workflow Q2 = "Loop", branch into a **nested 2-question
sub-menu**:

```
Q-loop-1 [single]:  "Iteration budget?"
  - 1 (try once)
  - 5 (quick refinement)
  - 10 (standard)
  - 100 (heavy convergence)
  - until-convergence (no cap; user must interrupt)

Q-loop-2 [multiSelect]:  "Stop conditions (any-match stops)"
  - Tests green
  - Gatekeeper green
  - Coverage at 100%
  - No new files changed in last iteration
  - User interrupt only
```

This is the "loop is the bridge selectable while configuring workflow"
the user asked for.

### Category 4: Audit (already shipped — multiSelect axes)

Done in `7ee8679` (audit:axis menu). 4 axes pickable; token-bloat
direct-only. **No further action needed for this category.**

### Category 5: Brain (multi-verb checklist)

`/kaizen:brain` (already exists as multi-verb parent). **Add menu** to
its empty-args invocation:

```
Q [multiSelect]:  "Brain operations?"
  - Capture (drop a thought)
  - Audit (scan recent sessions for promotion candidates)
  - Evolve (consolidate + cluster Notes)
  - Index (refresh brain.db)
  - Promote (project-memory → brain Notes)
  - Migrate (relocate brain dir)
  - Status (counts + Persona present check)
  - Seed (init defaults — for new installs)
```

### Category 6: Discovery (semantic search checklist)

`/kaizen:discovery` — **new** wrapper that bundles 4 commands:

```
Q1 [multiSelect]:  "What to index?"
  - Codebase (onboard)
  - Knowledge base (knowledge)
  - Claude API/Code docs (claude-docs)
  - Web content (scrape)

Q2 [single]:  "Action?"
  - Build/refresh index
  - Search
  - Stats
```

Backs to `/kaizen:onboard`, `/kaizen:knowledge`, `/kaizen:claude-docs`,
`/kaizen:scrape` per Q1 pick.

## Implementation plan (Phase 4)

### Phases (1 commit per phase)

- [ ] **P1**: Extend `/kaizen:setup` menu (be7638b) — add Q1 master
   action picker + branch into existing 4-question custom flow + add
   detect-stack-driven defaults path. Update tests.
- [ ] **P2**: New `/kaizen:workflow` slash command (4 questions:
   scope / run-mode / disciplines / threshold). Persists to
   `<repo>/.kaizen/workflow.json` OR `~/.claude/.kaizen/workflow-global.json`.
   Schema for the persisted config. Tests.
- [ ] **P3**: Loop sub-menu — nested under workflow Q2=Loop. 2
   questions (budget + stop-conditions). `/kaizen:loop` standalone
   stays as alias.
- [ ] **P4**: Extend `/kaizen:brain` (empty-args) with multiSelect
   verb checklist.
- [ ] **P5**: New `/kaizen:discovery` wrapper bundling onboard /
   knowledge / claude-docs / scrape.
- [ ] **P6**: Shared menu library — extract the AskUserQuestion
   orchestration into `skills/menu/SKILL.md` with reusable patterns
   (single-pick / multi-pick / branching / persist).
- [ ] **P7**: Menu lint — extend `kaizen-yaml lint` (or new
   `kaizen-menu lint`) to verify menu commands declare AskUserQuestion
   in allowed-tools, document the 4-question/4-option limits, etc.

### Out of scope (deferred to next plan)

- Menu telemetry (dxm event per menu fire). YAGNI today.
- Auto-pre-select based on most-chosen (need data first). YAGNI.
- Re-naming workflow schemas to align with cluster taxonomy.

## Iron-law + discipline checklist

Per `kaizen:plugin-development`:

- [ ] Every new CLI script has a paired `bin/kaizen-*` wrapper (P2,
   P5 if scripts ship)
- [ ] Every new hook honors `KAIZEN_<X>_DISABLE` knob (no hooks
   planned this round — menu work is command-only)
- [ ] Every new permission entry lands in `plugin.json` same commit
   (P2-P5 will need permissions for the new slash commands)
- [ ] Tests sandbox via env vars where applicable
- [ ] `progress.md` row per structural change

## Per-phase TDD shape

Each P# above:

1. RED — write contract tests for the menu (frontmatter / questions /
   options / allowed-tools / arg-assembly mapping)
2. GREEN — write the slash command body (instructional for the agent)
   + any backing script
3. REFACTOR — apply KISS + DRY (extract shared menu helpers in P6)
4. REGRESSION — full test suite + gatekeeper

## Verification

After all phases land:

```
kaizen help                              # 58 → ~55 (some commands aliased away)
kaizen surface validate                   # all menus declared, no orphans
kaizen-yaml lint                          # all menu YAMLs parse
python3 -m unittest discover -s tests    # ~2700 tests (was 2643), 0 fail
/kaizen:setup                            # interactive 1-question master picker
/kaizen:workflow                          # 4-question scope+mode+disciplines+threshold
/kaizen:workflow → Loop                   # cascades into 2-question loop sub-menu
/kaizen:brain                             # multi-verb checklist
/kaizen:discovery                         # what-to-index + action picker
```

## Stats (target)

| Metric | Before | After |
|---|---|---|
| Total slash commands | 58 | ~55-58 (no removals — additions land as menu wrappers) |
| Memorization burden (top-level entry points) | 9 clusters | 6 menus (setup / workflow / audit:axis / brain / discovery / explicit one-offs) |
| AskUserQuestion-driven menus | 4 (mode, intake, setup partial, audit:axis) | 8-10 (after P1-P5) |
| Documented overlap candidates resolved | 0 of 4 | 2-3 (loop↔workflow, setup↔bootstrap-family) |

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Existing scripts/hooks depend on the legacy slash command names | Keep all current slashes as aliases; menus are additive |
| Multi-step menu confusing in CC's UI | Test against real AskUserQuestion render; bound to ≤4 questions per call |
| Persisted workflow config drifts from session-mode config | P2's schema explicitly says "inherits from session-mode unless overridden"; tests pin precedence |
| /workflow vs /kaizen:workflow collision | kaizen-side prefixes the bash exec; external /workflow stays untouched |
| Big-bang scope creep | Phased per the 7 P# items above; each is 1 commit |
