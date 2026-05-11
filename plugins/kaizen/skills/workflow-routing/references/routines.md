# Workflow Routines

Curated stage sequences. The script picks one based on the prompt verb (or `skill=` override). Each stage maps to a single skill and produces a named artifact that the next stage consumes.

## Stage Catalog

| Stage | Skill (frontmatter name) | Reads | Produces |
|---|---|---|---|
| explore | `codebase-exploring` | repo | structure note, entry points |
| detect-stack | `stack-detecting` | repo | stack profile (lang, framework, CI gates) |
| research | `topic-researching` | request + stack | external facts, version notes |
| analyze | `change-analyzing` | exploration + research | impact, blast radius, interfaces |
| audit | `proactive-auditing` | exploration | findings list (verified) |
| debug | `debugging-failures` | failing symptom | root cause + reproduction |
| fix | `bug-fixing` | root cause | minimal change + regression test |
| create-plan | `plan-creating` | analysis | durable plan file (agent-reusable) |
| create-tasks | `tasks-creating` | plan | per-phase task list inside the plan |
| execute-plan | `plan-executing` | plan | landed phases with status updates |
| execute-tasks | `tasks-executing` | task list | landed tasks with verification |
| review | `change-reviewing` | diff or plan | findings, blockers, sign-off |
| simplify | bundled `/simplify` | diff | applied fixes (reuse / quality / efficiency) |
| validate | `plan-validating` | diff + plan | go / no-go decision |
| batch-fanout | bundled `/batch` | migration brief | N PRs (one per unit) |
| report | `report-generating` | landed work | user-facing summary |

> `simplify` and `batch-fanout` invoke **bundled Claude Code commands** (`/simplify`, `/batch` — v2.1.63+). They run their own multi-agent fan-out internally, so the workflow's `subagent=` flag has **no effect** on these stages. Treat them as atomic from the orchestrator's perspective.

## TDD Mode (`tdd=yes`)

Pass `tdd=yes` on `/workflow` to enforce test-driven development on every mutating stage (`fix`, `execute-tasks`, `execute-plan`). The flag is persisted to `state.json.tdd_mode` and the `wf-stage` / `wf-phase` agents read it to switch on RED → GREEN → REFACTOR per task:

1. **RED:** write the failing test first, run it, confirm it fails for the *right* reason.
2. **GREEN:** write the minimum implementation to pass — no more.
3. **REFACTOR:** improve structure with tests still green.

The stage's existing `Verification:` command becomes the GREEN gate. Drift (test passing without an implementation, test failing for the wrong reason) is reported as `blocked`, never silently absorbed.

`tdd=no` (default) follows the routine's normal verification only. Use `tdd=yes` for `build-feature`, `fix-bug`, `refactor`, and `harden` when you want test-first discipline; skip it on `audit` (no edits) and `batch-migrate` (workers handle their own verification).

## Routine: `audit`

**Trigger words:** *audit, health check, find issues, what needs work*

```
explore → detect-stack → research → audit → analyze → review → create-plan → create-tasks
```

End-state: a durable plan at `plans/<date>-<topic>.md` with audit findings encoded as phases, each with verification commands. With `auto=yes`, the plan is then executed.

**Stage prompts (use these when invoking each skill):**
1. **explore** — "Map the structure of <area>. Identify entry points, public surface, and existing patterns."
2. **detect-stack** — "Detect language, framework, conventions, and CI gates for <repo>."
3. **research** — "Research current best practices and known issues for <stack> as of today. Note version-specific concerns."
4. **audit** — "Hunt for real bugs, weak contracts, and missing regression coverage in <area>. Verify each finding with code reference."
5. **analyze** — "For each verified audit finding, assess blast radius, affected interfaces, and risk."
6. **review** — "Review the audit findings + analysis for false positives. Order by severity × effort."
7. **create-plan** — "Turn the prioritized findings into a phased remediation plan. Include rollback notes for risky phases."
8. **create-tasks** — "Inside each phase, expand into concrete tasks with files and verification commands."

## Routine: `build-feature`

**Trigger words:** *build, add, implement, create, new*

```
explore → detect-stack → research → analyze → create-plan → create-tasks → execute-tasks → simplify → review → report
```

End-state (auto=yes): feature implemented + tested + reviewed + reported. End-state (auto=no): plan + tasks ready for human approval.

**Stage prompts:**
1. **explore** — "Map the code paths the new feature will touch."
2. **detect-stack** — "Confirm stack and existing patterns to follow."
3. **research** — "Research API/library options and pitfalls."
4. **analyze** — "List interfaces to extend, invariants to preserve, and risk."
5. **create-plan** — "Write a phased plan ending in a verified feature."
6. **create-tasks** — "Expand each phase into concrete tasks."
7. **execute-tasks** — "Implement tasks one at a time with per-task verification."
8. **review** — "Review the diff for correctness and missing tests."
9. **report** — "Summarize what landed, what was deferred, and any follow-ups."

## Routine: `fix-bug`

**Trigger words:** *fix, bug, broken, flaky test, regression*

```
debug → analyze → fix → simplify → review → validate → report
```

End-state: bug repaired with a regression test that fails before the fix and passes after.

**Stage prompts:**
1. **debug** — "Reproduce <symptom>. Isolate root cause with minimal evidence."
2. **analyze** — "Confirm blast radius. Are other code paths affected?"
3. **fix** — "Land the minimal repair plus a regression test."
4. **review** — "Review the diff for correctness and minimality."
5. **validate** — "Run the full verification suite. Confirm no regressions."
6. **report** — "Summarize root cause, fix, and verification result in one paragraph."

## Routine: `refactor`

**Trigger words:** *refactor, clean up, restructure, extract, rename*

```
explore → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate
```

End-state: behavior preserved, structure improved, every phase verifiable independently. Plan is agent-reusable so the refactor can pause and resume across sessions.

## Routine: `migrate`

**Trigger words:** *migrate, upgrade, port to, switch from*

```
research → explore → analyze → create-plan → create-tasks → execute-tasks → simplify → review → validate
```

End-state: migration landed in slices, each slice green-build-safe. Research stage front-loads version-specific gotchas.

## Routine: `harden`

**Trigger words:** *harden, secure, threat model, lock down*

```
explore → audit → analyze → create-plan → create-tasks → execute-tasks → review → validate
```

End-state: prioritized hardening fixes landed with security regression tests. Audit stage uses `agent-aegis` framing.

## Routine: `batch-migrate`

**Trigger words:** *batch migrate, batch refactor, across all, every file, sweep*

```
research → explore → detect-stack → analyze → batch-fanout → report
```

End-state: N pull requests (one per independent unit) opened by parallel worktree agents. The `batch-fanout` stage hands off to bundled `/batch`, which performs its own internal plan-approval and worker spawning.

**Use when** the change is sweeping (≥5 independent units) and each unit can land as its own PR. For tightly coupled changes use `migrate` instead.

**Stage prompts:**
1. **research** — "Research target patterns and gotchas for the migration."
2. **explore** — "Map every call site / file / module the migration will touch."
3. **detect-stack** — "Confirm test runner, lint, and CI gates each PR will need to pass."
4. **analyze** — "Decompose into 5–30 self-contained, independently-mergeable units. Each must be standalone."
5. **batch-fanout** — "Invoke `/batch <one-line migration brief>`. Wait for `/batch`'s plan-approval gate, then let it spawn worker PRs."
6. **report** — "Pull PR URLs from `/batch` output, store in `state.artifacts.prs`, summarize: N/M units landed."

## New Stage Invocation

**`simplify`** — invoke the bundled `/simplify` slash command on the working tree. If `git diff` is empty, skip with `advance simplify "skipped (no diff)"`. Otherwise run `/simplify` and let it apply fixes; advance with the count of issues addressed. Optional focus argument when relevant: `/simplify focus on memory efficiency`.

**`batch-fanout`** — invoke the bundled `/batch <brief>` slash command. The brief comes from the prior `analyze` stage (decomposition output). `/batch` runs its own internal plan→approval→spawn flow; the workflow's job is just to record PR URLs after `/batch` returns.

## Routine: `custom`

For ad-hoc sequences. Set the routine to `custom` and pass an explicit `skill=NAME` chain (advance through one skill at a time). The script will not auto-detect; the model must call `advance` with each next stage.

## Stage Composition Rules

- Every stage that lands changes is preceded by at least one read-only stage (explore / research / analyze).
- Every routine that produces a plan also produces tasks — never one without the other.
- Every routine that executes also reviews afterward.
- `validate` runs full verification (test suite + build) at the end of mutating routines.
- `report` is mandatory when `auto=yes` so the user sees what landed without scrolling chat.

## Anti-Patterns

- **Skipping context stages.** "Just create the plan" without explore + analyze → speculative plan.
- **Auto-mode without review.** Removing the final `review` from a build/refactor/migrate/harden routine to "save a turn" → bugs land unchecked.
- **Routine inflation.** Adding stages to look thorough when the work doesn't need them — pad stages have no artifact.
- **Stage merging.** Doing two stages in one model turn — defeats per-stage verification, makes resume impossible.
- **Re-running complete stages.** If `state.json` says a stage is `complete`, do not re-run it on resume; trust the state or stop and surface drift.

## When To Customize

Edit the `routine_stages` function in `scripts/workflow.sh` to add or modify routines. Keep these invariants:

- Every routine ends with a durable artifact (plan file, fix + test, or audit report).
- Read-only stages appear before mutating stages.
- A routine should be representable as a flat ordered list — no branches.
- Stages that are likely to need decomposition into tasks should be followed by `create-tasks`.
