<!-- DO NOT HAND-EDIT.

Generated from skills/workflow/domain/routines.yaml by
skills/workflow/application/codegen.py.

To change content, edit the yaml and run:
    python3 skills/workflow/application/codegen.py
or rely on refresh-cache.sh which invokes codegen before sync.
-->

# Workflow Routines

Routines are stage chains the kaizen workflow runs. Each stage maps to a skill via the stage-skill table in references/orchestration.md. Hardcoded routines are verb-detected from the user's prompt; schema routines opt in via `schema=<name>` on `/workflow init`.

## Quick reference

| Routine | Kind | Trigger words | Stages |
|---|---|---|---|
| `audit` | hardcoded | `audit`, `health check`, `find issues`, `what needs work` | explore → detect-stack → research → audit → analyze → review → create-plan → create-tasks |
| `build-feature` | hardcoded | `build`, `add`, `implement`, `create`, `new` | explore → detect-stack → research → analyze → create-plan → create-tasks → execute-tasks → simplify → review → ci-gate → report |
| `fix-bug` | hardcoded | `fix `, `bug`, `broken`, `flaky test`, `regression` | debug → analyze → fix → simplify → review → validate → ci-gate → report |
| `refactor` | hardcoded | `refactor`, `clean up`, `restructure`, `extract`, `rename` | explore → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate → ci-gate |
| `batch-migrate` | hardcoded | `batch migrate`, `batch refactor`, `across all`, `every file`, `sweep ` | research → explore → detect-stack → analyze → batch-fanout → report |
| `migrate` | hardcoded | `migrate`, `upgrade`, `port to`, `switch from` | research → explore → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate → ci-gate |
| `harden` | hardcoded | `harden`, `secure`, `threat model`, `lock down` | explore → audit → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate → ci-gate |
| `self-improving` | hardcoded | `self-improve`, `self improve`, `curate memory`, `review memory`, `promote learning`, `promote learnings`, `analyze memory`, `graduate this`, `what has claude learned`, `memory health` | explore → self-analyze → review → create-plan → create-tasks → execute-tasks → report |
| `custom` | hardcoded | — | — |
| `kaizen-default` | schema | — | research → explore → analyze → plan → tasks → execute → review → validate |
| `debug-with-pdb` | schema | — | reproduce → isolate → inspect → hypothesize → verify-cause → fix → regression → postmortem → investigate-deeper |
| `mcp-build` | schema | — | detect-stack → research → create-plan → create-tasks → write-server-skeleton → write-tools → register-mcp-json → register-permissions → smoke-handshake → validate-cache → report |
| `minimalist` | schema | — | specs → tasks |
| `spec-driven` | schema | — | analyze → design → tasks → decisions → implement → validate → reflect → handoff |
| `onion-tdd-strict` | schema | — | audit → design-layers → red-test → green-impl → refactor → adapters → composition → supervisor → trace-wire → verify |
| `ralph-loop` | schema | `ralph`, `ralph loop`, `ralph-loop`, `self-correcting loop`, `iterate until`, `stop-hook loop` | start → iterate → verify |
| `shim-and-sweep` | schema | `carve`, `carve out`, `carve-out`, `split crate`, `split this crate`, `shim`, `deferred deletion`, `deletion manifest`, `borg-loop`, `borg loop`, `F-FINAL`, `shim and sweep` | explore → analyze → characterize → create-plan → create-tasks → carve-with-shim → migrate-callers → drift-check → sweep → validate |

## Routing defaults (backstops)

When `detect_routine()` finds no matching trigger word, the loader returns the default routine. When `get_stages()` is called with an unknown name, it returns the default stage chain. Both live in `routines.yaml::defaults` so the yaml is the single source.

- **Fallback routine:** `build-feature`
- **Fallback stages:** `explore` → `analyze` → `create-plan` → `create-tasks`

## Stage → skill map

Every workflow stage with a 1:1 kaizen-plugin skill is listed below. Unmapped stages (`simplify` = bundled slash command, schema-routine internals like `red-test` / `green-impl`) resolve via per-schema artifacts or slash commands documented in `references/orchestration.md`.

| Stage | Skill |
|---|---|
| `analyze` | `kaizen:analyze` |
| `audit` | `kaizen:audit` |
| `ci-gate` | `kaizen:ci-gate` |
| `create-plan` | `kaizen:create-plan` |
| `create-tasks` | `kaizen:create-tasks` |
| `debug` | `kaizen:debug` |
| `detect-stack` | `kaizen:detect-stack` |
| `execute-plan` | `kaizen:execute-plan` |
| `execute-tasks` | `kaizen:execute-tasks` |
| `explore` | `kaizen:explore` |
| `fix` | `kaizen:fix` |
| `migrate` | `kaizen:migrate` |
| `refactor` | `kaizen:refactor` |
| `report` | `kaizen:report` |
| `research` | `kaizen:research` |
| `review` | `kaizen:review` |
| `self-analyze` | `kaizen:self-improving` |
| `supervisor` | `kaizen:supervisor` |
| `task` | `kaizen:task` |
| `tool-use` | `kaizen:efficient-tool-use` |
| `validate` | `kaizen:validate` |

## Routines

### `audit` (hardcoded)

Periodic comprehensive audit (per the synavos article: severity-classified,
formal-report-producing). Use before major releases, after critical
incidents, or when entering a new project.

**Triggers:** 'audit', 'health check', 'find issues', 'what needs work'

**Stages:** `explore` → `detect-stack` → `research` → `audit` → `analyze` → `review` → `create-plan` → `create-tasks`

**End state:** Durable plan at plans/<date>-<topic>.md with audit findings encoded as phases

### `build-feature` (hardcoded)

End-to-end feature build. Default routine when no other verb matches.
The `simplify` stage between execute-tasks and review applies the
bundled /simplify command to trim over-engineering before review.
`karpathy` adds diff-level scanners (complexity / surgical / assumption /
goal) before commit.

**Triggers:** 'build', 'add', 'implement', 'create', 'new'

**Stages:** `explore` → `detect-stack` → `research` → `analyze` → `create-plan` → `create-tasks` → `execute-tasks` → `simplify` → `review` → `ci-gate` → `report`

**End state:** Feature implemented + tested + reviewed + reported (auto=yes); plan + tasks ready for approval (auto=no)

**Coding skills cross-link:** `kaizen:solid`, `kaizen:kiss`, `kaizen:yagni`, `kaizen:karpathy`

### `fix-bug` (hardcoded)

Bug-fix loop with minimal-change discipline. Regression test is mandatory.

**Triggers:** 'fix ', 'bug', 'broken', 'flaky test', 'regression'

**Stages:** `debug` → `analyze` → `fix` → `simplify` → `review` → `validate` → `ci-gate` → `report`

**End state:** Bug repaired with a regression test that fails before the fix and passes after

**Coding skills cross-link:** `kaizen:kiss`, `kaizen:dry`

### `refactor` (hardcoded)

Restructure code without changing behavior. Plan is agent-reusable so
the refactor can pause and resume across sessions. `karpathy` enforces
surgical-changes discipline during execute-tasks.

**Triggers:** 'refactor', 'clean up', 'restructure', 'extract', 'rename'

**Stages:** `explore` → `analyze` → `create-plan` → `create-tasks` → `execute-tasks` → `simplify` → `review` → `validate` → `ci-gate`

**End state:** Behavior preserved, structure improved. Each phase verifiable independently.

**Coding skills cross-link:** `kaizen:dry`, `kaizen:boy-scout-rule`, `kaizen:kiss`, `kaizen:separation-of-concerns`, `kaizen:karpathy`

### `batch-migrate` (hardcoded)

Sweeping change (≥5 independent units) where each unit can land as
its own PR. Hands off to bundled /batch which spawns worker subagents.

**Triggers:** 'batch migrate', 'batch refactor', 'across all', 'every file', 'sweep '

**Stages:** `research` → `explore` → `detect-stack` → `analyze` → `batch-fanout` → `report`

**End state:** N pull requests opened by parallel worktree agents (one per independent unit)

### `migrate` (hardcoded)

Framework, version, API, or infrastructure migration. Research stage
front-loads version-specific gotchas.

**Triggers:** 'migrate', 'upgrade', 'port to', 'switch from'

**Stages:** `research` → `explore` → `analyze` → `create-plan` → `create-tasks` → `execute-tasks` → `simplify` → `review` → `validate` → `ci-gate`

**End state:** Migration landed in slices, each slice green-build-safe

**Coding skills cross-link:** `kaizen:convention-over-configuration`, `kaizen:dry`

### `harden` (hardcoded)

Security / reliability hardening. Audit stage uses the `agent-aegis`
framing for threat modeling.

**Triggers:** 'harden', 'secure', 'threat model', 'lock down'

**Stages:** `explore` → `audit` → `analyze` → `create-plan` → `create-tasks` → `execute-tasks` → `simplify` → `review` → `validate` → `ci-gate`

**End state:** Prioritized hardening fixes landed with security regression tests

**Coding skills cross-link:** `kaizen:law-of-demeter`, `kaizen:separation-of-concerns`

### `self-improving` (hardcoded)

System-level self-improvement routine. Analyzes project memory
(~/.claude/projects/<slug>/memory/) + brain Notes
(~/.claude/.kaizen/brain/Notes/pref-*.md), surfaces patterns ready for
promotion (recur >= 2 sessions for rules / >= 3 for skill
extraction), creates a plan for user approval, then executes the
promotions (writes destination file with proper frontmatter,
archives source, updates Persona.md `## Top Beliefs` linkage).

Subsystem usage: any routine can add the `self-analyze` stage to
invoke self-improving's `review` sub-flow inline — surfaces
promotion candidates as a read-only report without committing to
the full graduate-and-archive lifecycle. Typically run as the
final stage of a long session to capture what should land in
memory before the context window resets.

**Triggers:** 'self-improve', 'self improve', 'curate memory', 'review memory', 'promote learning', 'promote learnings', 'analyze memory', 'graduate this', 'what has claude learned', 'memory health'

**Stages:** `explore` → `self-analyze` → `review` → `create-plan` → `create-tasks` → `execute-tasks` → `report`

**End state:** Promotion candidates surfaced; approved learnings graduated to durable rules / brain Notes / new kaizen skills; source memory entries archived

**Coding skills cross-link:** `kaizen:boy-scout-rule`, `kaizen:yagni`

### `custom` (hardcoded)

Escape hatch — no verb match. User pins each stage explicitly with
`skill=NAME`. The script does not auto-detect; the agent calls
`advance` with each next stage manually.

**Stages:** (none — user-pinned via `skill=NAME`)

**End state:** User-specified stage chain via repeated skill=NAME advance calls

### `kaizen-default` (schema)

Mirrors the hardcoded default flow but adds declarative gates and
requires-tracking. Use when you want the structure of build-feature
with stronger gate enforcement.

**Schema:** `schemas/kaizen-default/schema.yaml`

**Stages:** `research` → `explore` → `analyze` → `plan` → `tasks` → `execute` → `review` → `validate`

**End state:** 8-stage generic workflow with per-stage requires gates

**Coding skills cross-link:** `kaizen:kiss`, `kaizen:dry`, `kaizen:solid`

### `debug-with-pdb` (schema)

Python pdb-driven debugging with an explicit verify-cause gate. The
gate forces hypothesis verification before fixing.

**Schema:** `schemas/debug-with-pdb/schema.yaml`

**Stages:** `reproduce` → `isolate` → `inspect` → `hypothesize` → `verify-cause` → `fix` → `regression` → `postmortem` → `investigate-deeper`

**End state:** Bug reproduced, verified, fixed with regression. Postmortem optional.

**Coding skills cross-link:** `kaizen:kiss`

### `mcp-build` (schema)

Codifies the kaizen-lint + kaizen-workflow build pattern. Use when
adding a new MCP server to the kaizen plugin.

**Schema:** `schemas/mcp-build/schema.yaml`

**Stages:** `detect-stack` → `research` → `create-plan` → `create-tasks` → `write-server-skeleton` → `write-tools` → `register-mcp-json` → `register-permissions` → `smoke-handshake` → `validate-cache` → `report`

**End state:** New kaizen MCP server registered + smoke-tested + cached

**Coding skills cross-link:** `kaizen:dry`, `kaizen:kiss`

### `minimalist` (schema)

Low-ceremony 2-stage flow for small features where full kaizen-default
is overkill.

**Schema:** `schemas/minimalist/schema.yaml`

**Stages:** `specs` → `tasks`

**End state:** Spec written (Given/When/Then or EARS) + tasks decomposed

**Coding skills cross-link:** `kaizen:kiss`, `kaizen:yagni`

### `spec-driven` (schema)

EARS requirements + Decision Records (adapted from GitHub
awesome-copilot spec-driven-workflow-v1).

**Schema:** `schemas/spec-driven/schema.yaml`

**Stages:** `analyze` → `design` → `tasks` → `decisions` → `implement` → `validate` → `reflect` → `handoff`

**End state:** EARS requirements + Decision Records + implementation + handoff doc

**Coding skills cross-link:** `kaizen:solid`, `kaizen:dry`

### `onion-tdd-strict` (schema)

Onion-DDD layering + TDD + cookbook supervisor + full trace. Strictest
schema; gate on every stage. User-tier (lives in ~/.claude/.kaizen/).

**Schema:** `~/.claude/.kaizen/schemas/onion-tdd-strict/schema.yaml`

**Stages:** `audit` → `design-layers` → `red-test` → `green-impl` → `refactor` → `adapters` → `composition` → `supervisor` → `trace-wire` → `verify`

**End state:** Layered code with RED→GREEN→REFACTOR + cookbook supervisor + full trace

**Coding skills cross-link:** `kaizen:solid`, `kaizen:dry`, `kaizen:kiss`, `kaizen:separation-of-concerns`

### `ralph-loop` (schema)

Self-correcting Stop-hook iteration loop. Cross-CLI (CC + Codex) via
shared .kaizen/loop.state.md. Same prompt re-fed each iteration; the
agent observes prior work in files + git history. Stops on exact
<promise>PHRASE</promise> match or --max-iterations limit.

Invoke via `/kaizen:loop "<prompt>" --max-iterations N --completion-promise "PHRASE"`
or `/workflow schema=ralph-loop` for workflow-stage composition. The
Stop hook lives at hooks/{claude,codex}/stop-ralph.sh; it's a silent
no-op when .kaizen/loop.state.md is absent.

**Triggers:** 'ralph', 'ralph loop', 'ralph-loop', 'self-correcting loop', 'iterate until', 'stop-hook loop'

**Schema:** `schemas/ralph-loop/schema.yaml`

**Stages:** `start` → `iterate` → `verify`

**End state:** Completion promise matched (state file removed) OR max-iterations hit (state file removed).

**Coding skills cross-link:** `kaizen:kiss`

### `shim-and-sweep` (schema)

Refactor with deferred-deletion discipline (originally shodan's
"borg-loop"). Every relocation leaves a 1-line re-export shim;
shims accumulate in a deletion manifest; one user-gated sweep
retires them all. Compile + tests green at every commit boundary.
Pairs with the kaizen pre_deletion_belief gate.

**Triggers:** 'carve', 'carve out', 'carve-out', 'split crate', 'split this crate', 'shim', 'deferred deletion', 'deletion manifest', 'borg-loop', 'borg loop', 'F-FINAL', 'shim and sweep'

**Schema:** `schemas/shim-and-sweep/schema.yaml`

**Stages:** `explore` → `analyze` → `characterize` → `create-plan` → `create-tasks` → `carve-with-shim` → `migrate-callers` → `drift-check` → `sweep` → `validate`

**End state:** Large refactor landed without mid-flight breakage; shims swept in one user-gated commit.

**Coding skills cross-link:** `kaizen:dry`, `kaizen:separation-of-concerns`, `kaizen:boy-scout-rule`, `kaizen:kiss`, `kaizen:yagni`

