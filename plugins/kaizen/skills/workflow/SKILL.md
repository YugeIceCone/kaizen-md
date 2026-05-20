---
name: workflow
description: Commit cadence + pre-commit gate + multi-stage routines (audit / build-feature / fix-bug / refactor / migrate / harden / debug / mcp-build / spec-driven / onion-tdd-strict). Triggers on "git workflow", "pre-commit hook", "commit discipline", "BACKLOG", "architecture log row", "plan-phase tick", "Conventional Commits", "pre-deletion gate", "core.hooksPath", "run a structured workflow", "build feature end-to-end", "fix bug end-to-end", "refactor with a plan", "audit the repo end-to-end". Read body in full before applying.
version: 2.0.0
---

# Workflow — discipline + orchestration in one skill

This skill unifies the two layers of kaizen's workflow surface:

1. **Discipline** — *how* to commit code: sizing model, pre-commit gates, architecture log, plan files, BACKLOG. Project-agnostic rules from `domain/git-discipline.yaml`.
2. **Orchestration** — *what* multi-stage routine to run end-to-end: `audit`, `build-feature`, `fix-bug`, `refactor`, `migrate`, `harden`, `batch-migrate`, `self-improving`, `custom` (hardcoded) plus 8 schema-driven routines (`kaizen-default`, `debug-with-pdb`, `mcp-build`, `minimalist`, `spec-driven`, `onion-tdd-strict`, `ralph-loop`, `shim-and-sweep`). Routines are declared in `domain/routines.yaml` and run via `scripts/ops/workflow.sh` (or the `mcp__plugin_kaizen_kaizen-workflow__*` MCP tools).

Discipline + orchestration overlap — every routine's `execute-tasks` stage commits code under the discipline rules. The yaml schemas make that overlap explicit.

## ⚠ Iron Law — read in full

Skip nothing. The sizing model, the pre-commit gate list, the routine catalog, and the stage-to-skill mapping only hold together. Skimming to the "Quick reference" table without reading the discipline section produces gates that pass syntactically while violating the rules they exist to enforce.

## Onion-DDD layout inside this skill

```
skills/workflow/
├── SKILL.md                          (presentation — narrative + concept primer)
├── domain/                           (pure data; no behavior)
│   ├── routines.yaml                 (17 routines: 9 hardcoded + 8 schema-driven)
│   ├── git-discipline.yaml           (12 pre-commit gates + sizing + format)
│   └── schemas/
│       ├── routine.schema.json
│       └── git-rules.schema.json
├── application/                      (loaders + codegen — MIGRATION BRIDGES to scripts/workflow/)
│   ├── _loader.py                    (yaml → typed dict, JSON Schema validated)
│   ├── codegen.py                    (regenerates references/{routines,git-discipline}.md)
│   └── _tests.py                     (17 tests)
└── references/                       (generated docs + hand-written orchestration/gates)

Post-v1.40 layout — adapters live at <plugin>/scripts/<cluster>/ outside this skill:
  scripts/ops/workflow.sh             (state machine; reads routines.yaml via _loader)
  scripts/mcp/workflow_mcp.py         (9 MCP tools wrapping workflow.sh)
  scripts/git-hooks/pre-commit.sh     (reads git-discipline.yaml)
  scripts/install/refresh-cache.sh    (invokes codegen.py before sync)
```

`references/` contents: `routines.md` + `git-discipline.md` + `code-router.md` (GENERATED via `application/codegen.py`); `orchestration.md`, `gates.md`, `node-flow.md`, `integration.md`, `hooks-config.md`, `plugin-root-resolution.md`, `plugin-surface-map.md`, `mermaid-flowchart-api.md`, `backlog-template.md` (HAND-written).

Dependency direction: presentation → application → domain. Adapters → application → domain. No reverse edges. New rules go in `domain/`; new behavior in `application/`; new I/O in `scripts/`.

## Routine catalog (Quick reference)

The 17 routines, by kind. See `references/routines.md` (generated) for the full per-routine breakdown including stage descriptions and coding-skills cross-links.

| Routine | Kind | Trigger words | Stages |
|---|---|---|---|
| `audit` | hardcoded | audit, "health check", "find issues" | explore → detect-stack → research → audit → analyze → review → create-plan → create-tasks |
| `build-feature` | hardcoded | build, add, implement, create, new (default fallback) | explore → detect-stack → research → analyze → create-plan → create-tasks → execute-tasks → simplify → review → report |
| `fix-bug` | hardcoded | "fix ", bug, broken, "flaky test" | debug → analyze → fix → simplify → review → validate → report |
| `refactor` | hardcoded | refactor, "clean up", restructure | explore → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate |
| `migrate` | hardcoded | migrate, upgrade, "port to" | research → explore → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate |
| `harden` | hardcoded | harden, secure, "threat model" | explore → audit → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate |
| `batch-migrate` | hardcoded | "batch migrate", "across all", "sweep " | research → explore → detect-stack → analyze → batch-fanout → report |
| `self-improving` | hardcoded | "self-improve", "curate memory", "review memory", "promote learning", "graduate this", "memory health" | explore → self-analyze → review → create-plan → create-tasks → execute-tasks → report |
| `custom` | hardcoded | (user-pinned via skill=NAME) | (empty) |
| `kaizen-default` | schema | (schema=kaizen-default) | research → explore → analyze → plan → tasks → execute → review → validate |
| `debug-with-pdb` | schema | (schema=debug-with-pdb) | reproduce → isolate → inspect → hypothesize → verify-cause → fix → regression → postmortem → investigate-deeper |
| `mcp-build` | schema | (schema=mcp-build) | detect-stack → research → … → smoke-handshake → validate-cache → report |
| `minimalist` | schema | (schema=minimalist) | specs → tasks |
| `spec-driven` | schema | (schema=spec-driven) | analyze → design → tasks → decisions → implement → validate → reflect → handoff |
| `onion-tdd-strict` | schema (user) | (schema=onion-tdd-strict) | audit → design-layers → red-test → green-impl → refactor → adapters → composition → supervisor → trace-wire → verify |
| `ralph-loop` | schema | "ralph", "ralph loop", "self-correcting loop", "iterate until", "stop-hook loop" | start → iterate → verify |
| `shim-and-sweep` | schema | "carve", "carve out", "split crate", "shim", "deferred deletion", "borg-loop", "shim and sweep" | explore → analyze → characterize → create-plan → create-tasks → carve-with-shim → migrate-callers → drift-check → sweep → validate |

Verb-detection: lowercase the prompt, iterate `routines.yaml` entries in declaration order, return the first routine whose `trigger_words` substring-match. `batch-migrate` comes before `migrate` in the yaml so "batch migrate all files" routes correctly. Unmatched prompts default to `build-feature`.

## Sizing model — NEVER by clock-time

Probe via trace + sem + grep. Count actual files, manifest edits, trait moves, cross-context hops. Never grade by hours.

| Tier | Threshold | Destination |
|---|---|---|
| Micro | ≤3 files, 0 manifest edits, 0 trait moves | `.kaizen/workflow/backlog.json` (stays a checkbox) |
| Split into siblings | 4–15 files OR 1 manifest OR 1 trait move | Sibling micros on backlog.json |
| Plan file | ≥16 files OR ≥2 manifests OR cross-context OR carve-out trigger | `plans/<date>-<slug>.md` |
| Architecture log row | New crate / file-set carve / locked-rule / plan executed / dep-direction reversal | `.kaizen/workflow/progress.md` (append-only table) |

Full sizing rules + worked examples: `references/git-discipline.md` (generated from yaml).

## Pre-commit gates (12)

The pre-commit hook iterates `domain/git-discipline.yaml::pre_commit_gates[]` in order. Each gate is one of `error` (block), `warn` (notify), or `info` (log). Highlights:

- **`compile_barrier`** — `cargo check` / `tsc --noEmit` / `mypy` / `go build`. Cached by staged-sha; only runs when content changed.
- **`backlog_schema_valid` + `backlog_md_in_sync`** — backlog.json validates; backlog.md not hand-edited.
- **`structural_change_logs_to_progress`** — new crate / carve / locked-rule diff requires a `progress.md` row in the same commit.
- **`plan_phase_tick`** — landing a plan phase requires `- [x]` checkbox tick in the same commit (no separate "tick the boxes" follow-up).
- **`no_deletion_without_auth`** — `git rm` without `KAIZEN_ALLOW_DELETE=1` blocks. Pre-deletion belief gate.
- **`no_volatile_data_in_claude_md`** — CLAUDE.md MUST NOT contain commit SHAs, dates, or LOC numbers (those live in `progress.md`).
- **`conventional_commit_subject`** — `commit-msg.sh` enforces the format.

Full list with probe commands + bypass envs in `references/git-discipline.md`.

## Pre-deletion belief

`git rm` triggers a scan of `~/.claude/.kaizen/brain/Persona.md ## Top Beliefs` and the project's `MEMORY.md`. Hits → confirm-or-abort with the user. Bypass for one commit: `KAIZEN_ALLOW_DELETE=1 git commit ...`. This belief is non-negotiable; the gate is the enforcement, but the *discipline* is to never reach for deletion as a shortcut around an obstacle.

## Plan files vs BACKLOG vs architecture log

Three durable artifacts; one per scale:

- **`.kaizen/workflow/backlog.json`** (rendered to `.md`) — micro work, edited via `backlog.py`. NEVER hand-edit the `.md`.
- **`plans/<date>-<slug>.md`** — ≥3-phase work or carve-out. Status block at top; phase checkboxes; verification commands; resume protocol.
- **`.kaizen/workflow/progress.md`** — append-only architecture log. One row per structural change in the SAME commit. No sha column (`git log --grep` resolves rows).

The split is enforced at gate time. Adding "I'll just do this micro work as a plan file" without ≥3 phases is the anti-pattern.

## Orchestration loop (when running `/workflow`)

1. **Init.** `workflow.sh init "<prompt>"` writes `.kaizen/workflow/state.json` from `routines.yaml`. State includes `stages[]`, `current`, `routine`, `subagent_mode`, `auto_mode`, `tdd_mode`, `schema_name`.
2. **Run the current stage.** Invoke the matching skill (see Skill weaving table below).
3. **Capture artifacts.** `workflow.sh artifact <key> <value>` records durable outputs (plan_file, audit_report, mcp_server, fix_diff). Schema-driven workflows validate the key against `apply.gate.requires`.
4. **Advance.** `workflow.sh advance <stage> "<one-line result>"`. Gate enforcement (v1.30.0+): if the schema declares `requires: [...]` for the current stage, those artifacts must exist before the advance succeeds.
5. **Pause point.** `auto=no` after `create-tasks` to let the user approve plan+tasks before `execute-tasks` runs.
6. **Final report.** `report` stage summarizes what landed.

MCP equivalents under the `kaizen-workflow` server: `workflow_init`, `workflow_advance`, `workflow_artifact`, `workflow_branch`, `workflow_status`, `workflow_list_schemas`, `workflow_show_schema`, `workflow_validate_schema`. Use these instead of typing slash commands when you want autonomous flow.

## Subagent + auto + tdd modes

- **`subagent=no`** (default) — single-session run.
- **`subagent=yes`** — read-only stages (explore / research / audit / analyze / review) dispatch to subagents.
- **`subagent=full`** — execution stages dispatch too; requires agent-reusable plan with phase independence.
- **`auto=no`** (default) — pause for approval after `create-tasks`.
- **`auto=yes`** — chain end-to-end; pair with the Stop-hook config in `references/orchestration.md`.
- **`tdd=no`** (default) — normal verification only.
- **`tdd=yes`** — enforce RED → GREEN → REFACTOR on every mutating stage. The stage's verify command becomes the GREEN gate. This flag is the workflow-level toggle for the **`verify-before-execution`** discipline (apply nothing without RED proof of need + GREEN proof of safety); recommended for any routine that mutates production code or shared state. See `kaizen:verify-before-execution` for the full RED-GREEN matrix and integration rules.

## Cross-link to coding-skills (the 8 principles + karpathy)

`routines.yaml` declares `coding_skills: [...]` per routine. These are the principles to apply during the routine's mutating stages. Examples:

- `build-feature.coding_skills = [solid, kiss, yagni, karpathy]` — default skills for new code
- `refactor.coding_skills = [dry, boy-scout-rule, kiss, separation-of-concerns, karpathy]`
- `fix-bug.coding_skills = [kiss, dry]` — minimal change, deduplicate when touched
- `migrate.coding_skills = [convention-over-configuration, dry]`

Each links to the corresponding `kaizen:*` skill (kaizen:solid, kaizen:kiss, etc.). The skill bodies are NOT absorbed into this file — they remain independent. The cross-link is just a routing hint: "during execute-tasks for refactor, also have these principles in context."

**`kaizen:karpathy`** (v1.32.0+) is the active-coding-discipline sibling — same family, different angle. Where the 8 classic principles teach *what to do*, karpathy enforces *what NOT to do* with diff-level Python scanners (complexity / surgical / assumption / goal). Run `kaizen-karpathy-check` before commit on non-trivial diffs.

## Skill weaving (stage → skill map)

| Routine stage | Skill |
|---|---|
| `explore` | `kaizen:explore` (codebase exploring) |
| `detect-stack` | `kaizen:detect-stack` |
| `research` | `kaizen:research` |
| `analyze` | `analyze` (built-in) |
| `audit` | `kaizen:audit` |
| `debug` | `kaizen:systematic-debugging` |
| `fix` | `fix` (built-in) |
| `create-plan` | `kaizen:writing-plans` / `create-plan` |
| `create-tasks` | `create-tasks` |
| `execute-plan` | `kaizen:executing-plans` |
| `execute-tasks` | `execute-tasks` + **`kaizen:verify-before-execution`** (RED-GREEN gate per task) |
| `review` | `kaizen:review` / `review` (+ `kaizen:verify-before-execution` for in-flow cleanups) |
| `simplify` | bundled `/simplify` |
| `validate` | `validate` |
| `batch-fanout` | bundled `/batch` |
| `report` | `report` |

`simplify` and `batch-fanout` are bundled Claude Code commands (`/simplify`, `/batch` v2.1.63+) that run their own internal multi-agent fan-out — `subagent=` has no effect on these atomic stages.

## When to redirect

- single-skill request ("just create a plan") → invoke that skill directly, skip the workflow
- inspect active workflow → `workflow.sh status` or `workflow_status` MCP tool
- stuck → mark stage `blocked` in state, surface cause, ask user
- drop active workflow → `workflow.sh reset`

## Authoring new routines

To add a routine (e.g., a custom CI verification flow):

1. Add an entry to `domain/routines.yaml`. Set `kind: hardcoded` if verb-detected, `kind: schema` if opt-in via `schema=<name>`.
2. Add stage names to the catalog if any are new.
3. Update the `coding_skills:` cross-link if applicable.
4. Run `python3 application/codegen.py` (or just `refresh-cache.sh`) — regenerates `references/routines.md`.
5. Run `python3 application/_tests.py` — should still pass.
6. For `kind: schema`, also create `schemas/<name>/schema.yaml` with the detailed artifact/gate/branch declaration. Run `workflow_runner.py validate <name>`.

No bash editing needed. Adding a routine = editing yaml.

## Additional resources

- `references/routines.md` — full per-routine breakdown (GENERATED — edit yaml instead)
- `references/git-discipline.md` — gates + sizing + commit format (GENERATED — edit yaml instead)
- `references/orchestration.md` — subagent dispatch templates, parallel fanout, Stop / SessionStart / PreToolUse hook recipes
- `references/gates.md` — `apply.gate.requires` semantics, artifact-key validation, `--force` bypass + audit trail

## Bash invocation discipline

CC's permission matcher reprompts on certain compound shapes even when `Bash(*)` is globally allowed. Six rules in `domain/git-discipline.yaml::bash_invocation_discipline` minimize reprompts AND keep destructive ops isolated for clearer audit:

1. **`rm_in_isolation` (hard)** — never combine `rm` / `rm -rf` with other ops in one Bash call
2. **`export_over_envprefix` (soft)** — `export VAR=1; cmd` over `VAR=1 cmd` inline
3. **`split_compound_when_destructive` (hard)** — break `setup && test && cleanup` into separate Bash calls
4. **`mktemp_for_scaffolds` (soft)** — `TMPDIR=$(mktemp -d -t pfx-XXXX)` over hardcoded `/tmp/<name>`
5. **`find_delete_for_dir_empty` (soft)** — `find <path> -mindepth 1 -delete` over `rm -rf <path>/*`
6. **`scope_tool_calls_narrowly` (soft)** — one logical op per Bash call; avoid 5+ `&&` chains

Full rationale + good/bad examples: `references/git-discipline.md` (generated). Optionally enforced via PreToolUse hook (advisory; non-blocking) — see `references/orchestration.md`.

## Rules summary

- One stage at a time, in routine order — never skip ahead.
- Update `state.json` via `advance` after every completed stage.
- Honor `subagent=` and `auto=` modes — never silently override.
- Stop and report on any stage failure — never silently retry.
- Every routine ends with a durable artifact (plan, fix+test, or audit report).
- Pre-deletion belief: no `git rm` without explicit user authorization. Period.
- Bash discipline: `rm` in its own call; never compound destructive ops.
