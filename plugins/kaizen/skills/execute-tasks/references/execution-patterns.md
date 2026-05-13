# Execution Patterns

Operational patterns for running a batch of task briefs cleanly. Pick the section that matches the situation rather than reading top-to-bottom.

## Status Tracking

Pick one durable surface for status and update it after every task. Do not split status across multiple surfaces — that is how progress gets lost.

### Pattern: Inline checklist in plan file

Best when tasks live inside an approved plan.

```markdown
## Tasks

- [x] Task 1: Extract Foo interface — verified `cargo test -p foo` (commit abc1234)
- [x] Task 2: Migrate bar module — verified `cargo test -p foo` (commit def5678)
- [ ] Task 3: Remove legacy path — pending
- [ ] Task 4: Cleanup callers — pending
```

Edit the file in place after each task completes. Reference the verifying commit or diff, not just `done`.

### Pattern: Standalone task file with status block

Best when tasks are batch-loaded from a `tasks-creating` output and the plan does not own them.

```markdown
### Task 2: Migrate bar module

- Status: ✅ done — 2026-04-26 (commit def5678)
- Verification: `cargo test -p foo` — passed
- Notes: extracted shared helper `bar_into_iface` to keep migration self-contained.
```

### Pattern: Inline reporting back to the user

Best when no durable surface exists and the user is tracking progress in chat.

```
Task 1 ✅ — Extract Foo interface (cargo test -p foo passed)
Task 2 ✅ — Migrate bar module (cargo test -p foo passed)
Task 3 ⏳ — Remove legacy path (in progress)
```

Update after each task, not in a single dump at the end.

## Mid-Batch Failure Recovery

A task fails verification. Choose a recovery mode based on cause, not desperation.

1. **Test failure pinpoints the task's own change.** Diagnose with **debugging-failures**, fix inside the task scope, re-verify, mark done.
2. **Test failure points at an earlier task's change.** Stop the batch. The earlier task was incorrectly marked complete. Re-open it; verify the regression; fix or revert.
3. **Test failure is unrelated (flaky test, environment).** Capture the failure with `git notes add` against HEAD; do not paper over with retries. Surface to the user and ask whether to proceed with the rest of the batch.
4. **Scope creep.** The task needs files outside its declared scope to land. Stop. Either expand the brief explicitly (route back to **tasks-creating**) or split the task. Do not silently widen scope.
5. **Dependency error.** A later task assumed something an earlier task did not produce. Stop and re-route to **tasks-creating** — the dependency graph was wrong.

Never:

- skip a verification to "make progress"
- mark a task complete when its verification did not pass
- proceed to the next task on a yellow signal
- run `--no-verify` or equivalent bypasses

## Partial-Batch Handoff

If the session ends or runs out of context before the batch is finished:

1. **Mark current state honestly.** Tasks completed and verified, tasks blocked, tasks not yet started.
2. **Capture the in-progress task's exact state.** What was changed, what was tried, what verification result was last observed.
3. **Write the handoff with file paths, branch name, and any uncommitted changes.** Use the **handoff** skill if available.
4. **Surface invariants that still hold and any that do not.** A test you broke and did not fix counts as broken — say so.

A clean handoff is reproducible: the next session should be able to pick up the next unstarted task without re-deriving context.

## Integration Verification

After every task in the batch is verified individually, run a broader pass before declaring the batch done:

- **Full test suite** (`pnpm test`, `cargo test --all`, `pytest`) — not the targeted subset each task ran.
- **Build / typecheck** (`pnpm build`, `cargo build --all-targets`, `tsc --noEmit`).
- **Lint** if the project uses it as a gate.
- **Smoke test** the intended user-visible flow if the change touches runtime behavior.

A failure here means the tasks composed badly even though each passed in isolation. Common causes:

- two tasks each mocked the same dependency in incompatible ways
- a refactor task removed a symbol a later task still used through an indirect path
- one task introduced a feature flag default change while another assumed the old default

When integration fails, **do not retroactively edit per-task status** — instead open a follow-up task that fixes the integration gap.

## Reporting Done

A complete batch report includes:

- ✅ tasks completed, with verification command and short outcome note
- ⚠ tasks completed but with caveats (e.g. flaky test ignored — see git note)
- ❌ tasks blocked or rolled back, with cause
- ⬜ tasks not started, with reason (out of scope, dependency missing)
- integration verification result (passed / failed with link)
- follow-up tasks the user should know about

Resist the urge to paper over partial completion as success. A two-sentence "X done, Y blocked because Z" is more useful than a green tick on incomplete work.

## Anti-Patterns

- **Front-loading verification.** Running tests once at the end and calling each task done in retrospect — masks regressions to a specific task.
- **Verification by vibes.** "Should be fine, the diff is small." Always run the declared command.
- **Status drift.** Updating status hours late, in batches, or only at session end.
- **Silent scope expansion.** Touching files outside the brief because "they were in the way".
- **Retry-until-green.** Re-running a flaky verification until it passes by chance instead of investigating.
- **Skipping integration check.** Per-task green is necessary, not sufficient.

## When To Hand Back to tasks-creating

Stop the batch and route back if any of these are true:

- task briefs are missing files, scope, or verification commands
- the dependency graph is unclear or appears cyclic
- discovery during execution invalidates the original plan
- the user changes acceptance criteria mid-batch

Do not absorb planning work silently — surface the gap.
