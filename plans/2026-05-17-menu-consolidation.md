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

- [x] **P1**: Extend `/kaizen:setup` menu (be7638b) — add Q1 master
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

---

## Phase P0 (prerequisite) — retire 4 deprecation-alias slashes

Lands BEFORE P1 so the menu surface the user starts from is already
canonical. Single atomic commit, verified during 2026-05-17 PM session
(see handoff `2026-05-17_17-39_menu-consolidation-analysis-verified-4-d.yaml`).

### Scope (verified against source)

**Delete (KAIZEN_ALLOW_DELETE=1, all four ship `DEPRECATED ALIAS` marker):**

- `plugins/kaizen/commands/rule.md` → `/kaizen:rules`
- `plugins/kaizen/commands/mode.md` → `/kaizen:session-mode`
- `plugins/kaizen/commands/migrate-paths.md` → `/kaizen:migrate paths`
- `plugins/kaizen/commands/refresh-cache.md` → `/kaizen:update` (update.sh:124 always chains refresh-cache)

**Update tests (drop alias-existence assertions):**

- `tests/test_mode_command.py:22-30` — drop `test_deprecated_alias_exists_and_marks_itself`
- `tests/test_intent_mode.py:99-113` — assert `/kaizen:session-mode` not `/kaizen:mode`

**Migrate live refs to canonical slash names (10 files):**

- `skills/intent/domain/intents.yaml` — 6 occurrences (intent suggestions served live to users)
- `skills/behaviour-config/SKILL.md` — 4 occurrences (`/kaizen:rule` → `/kaizen:rules`)
- `skills/auto-handoff/SKILL.md` — 1 occurrence (`/kaizen:mode` → `/kaizen:session-mode`)
- `skills/agent-formatting/SKILL.md` — 6 occurrences (`/kaizen:refresh-cache` → `/kaizen:update`)
- `skills/agent-brief/SKILL.md` — 1 occurrence
- `hooks/claude/userprompt-skills-reminder.sh` — 1 comment
- `skills/workflow/scripts/migrate.sh:294` — 1 comment
- `plugins/kaizen/README.md:135` — 1 line
- `CLAUDE.md` — strike migrate-paths from known-overlap row
- `.kaizen/workflow/progress.md` — architecture-log row (dogfood gate)

**Skipped (historical accuracy — do NOT rewrite):**

- `plugins/kaizen/CHANGELOG.md` — ~10 historical refs stay factual

### Scrapped from earlier proposals (with reasons)

| Proposal | Why scrapped |
|---|---|
| Rename `karpathy-check.md` → `karpathy.md` | `Skill(kaizen:karpathy)` already exists — slash/skill namespace collision. The `-check` suffix is the disambiguator. Convention exception. |
| Rename `vibe-check.md` → `vibe.md` | Same — `Skill(kaizen:vibe-check)` exists. |
| Fold `gatekeeper` absorbs `self-audit / agent-self-audit / ci-gate` | Frontmatter shows 4 distinct jobs with different exit-code contracts + runtimes; not flavors of one verdict. |
| Fold `status` absorbs `health` | Different exit-code contracts — status is read-only display, health is CI-lint diagnostic that exits 1 on errors. |
| Fold `trace` absorbs `trace-search` | trace.py CLI has explicit `query` subcommand; would need new arg-detect behavior in the bin that isn't there today. |

### Execution sequence (RED→GREEN)

1. Update `test_mode_command.py` + `test_intent_mode.py` asserts → run suite → expect RED on intent-yaml mismatch
2. Update `intents.yaml` + 8 doc refs → run suite → GREEN
3. `KAIZEN_ALLOW_DELETE=1 git rm` the 4 alias files
4. Add `.kaizen/workflow/progress.md` architecture-log row
5. Single commit — `refactor(commands): retire 4 deprecation-alias slashes`
6. Verify — `kaizen-gatekeeper check --all` + `kaizen-metrics skips` + full unittest suite

### Stats target

- Slash commands: 58 → 54 (4 deletes, zero functionality loss)
- plugin.json churn: 0 (no manifest refs to the deprecated names)
- Test delta: -1 (dropped alias-existence test) + 0 net (intent-yaml asserts redirected)

---

## Observability findings — context-pressure surface

Investigation triggered by an apparent "context 85%" message that
didn't match the user's perception. Dug across hook → trace → DXM →
slash-command path. **Three streams**, each with a different contract.
Ground truth this session (from DXM):

```
context.warn.red          pct=85  tokens=170964  limit=200000  ts=1779039579.46
auto_handoff.requested    pct=85  threshold=85   bucket=threshold-block
```

So the hook's "context 85%" message was correct (pct=85.48). The
"unknown" output from `/kaizen:context` and the empty `Stop-auto-handoff`
trace payload are not defects — they're consequences of how the three
streams are partitioned. Correct framing below.

### The three streams + their contracts

| Stream | Purpose | Payload policy | Source-of-truth for context pct? |
|---|---|---|---|
| **trace** (`~/.claude/.kaizen-trace/events.jsonl`) | Lightweight observability log; hook firings + tool dispatches | Session-id-only since CHANGELOG v1.6.1 privacy fix — `_trace.sh` extracts ONLY `session_id`, never payload | NO — by design |
| **DXM** (`~/.claude/.kaizen/dxm/events-<sid>.jsonl`) | Durable mid-work state mirror over CC's JSONL | Full structured payload per event | YES — `context.warn.*` + `auto_handoff.requested` events carry `{pct, tokens, limit, peak_*}` |
| **`/kaizen:context` slash** | Quick "where am I" check | Reads `CLAUDE_CONTEXT_TOKENS` env OR stdin JSON | Returns "unknown" when neither present — no DXM fallback wired |

### Defect candidates (filed as separate from menu consolidation)

| # | Defect | Severity | Fix shape |
|---|---|---|---|
| **D1** | `/kaizen:context` returns "unknown" when CLAUDE_CONTEXT_TOKENS env is absent, even though DXM holds the freshest measurement | medium | Add fallback in `commands/context.md` body → query `kaizen-dxm tail --session $(kaizen-dxm session-id) --evt 'context.warn.*'` for the most recent pct/tokens. Already-trapped data; just unwire the env-only constraint. |
| **D2** | Hook message "context 85%, threshold 85%" looks like an echo; users can't tell whether 85 is measured or hardcoded threshold | low | Re-template `auto_handoff.py` message templates (`AUTO_HANDOFF_MSGS` dict) to show both as separate signals: `"context at {pct}% (measured), threshold {threshold}% (configured)"`. |
| **D3** | DXM has the data but the trace doesn't — cross-querying ("when did context cross 75%") requires switching tools | low | YAGNI — accept the two-store split. The intentional payload-stripping in trace is the right call (privacy + size). Pair the two with a small reader: `kaizen-context history` that joins trace timestamps with DXM `context.warn.*` payloads. **Defer**. |

### What is NOT a defect (corrected from earlier claim)

- ❌ "Trace shows empty `data` field on `Stop-auto-handoff`" — **not a defect.** That's the v1.6.1 privacy contract. The data IS captured, in DXM, where it belongs (`auto_handoff.requested` event with full payload). My earlier finding mis-framed the contract split as a defect.
- ❌ "Hook message is a threshold echo" — **not entirely.** The hook DOES measure; the message template just doesn't visibly separate the two numbers when they're equal. D2 above is the cosmetic fix.

### Skill discipline take-away

When investigating a "the system is wrong" claim:

1. **Find the data store that owns the value** — three stores (trace / DXM / state.json) each have a different contract; don't blame one for missing data the other holds.
2. **Read the source contract before calling it a defect** — `_trace.sh` literally says "never the full payload — see CHANGELOG v1.6.1 fix" in its docstring. That was findable in 30 seconds.
3. **Verify against raw ground truth** before adjusting beliefs — `grep '"pct"' ~/.claude/.kaizen/dxm/events-<sid>.jsonl` returned the exact measurement (pct=85, tokens=170964/200000). User and hook were both right.

This take-away applies BEYOND this session — convention-over-config
rule: "Conventions must be discoverable. A convention that exists only
in one developer's head is not a convention — it's a trap." The v1.6.1
trace-payload-stripping rule IS documented (in `_trace.sh`'s
docstring) — but not surfaced at the "is this a defect?" decision
point. Consider adding a one-line cross-reference in `commands/trace.md`
+ `commands/context.md` pointing at "where to find the actual pct"
(DXM, not trace).
