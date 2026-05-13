# Task Templates

Skeletons and worked examples for common task shapes. Copy a skeleton, fill in concrete files and verification commands, then hand the brief to **task-performing** or batch it for **tasks-executing**.

## Skeleton

```markdown
### Task N: <imperative title>

- **Objective**: <one sentence, action-verb led>
- **Scope**: <what is in / out>
- **Files**: <concrete paths or symbols>
- **Invariants**: <contracts that must still hold>
- **Verification**: <exact command(s) that prove done>
- **Blocked-by**: <task ids or "none">
- **Blocks**: <task ids or "none">
- **Redirect signals**: <symptoms that mean stop and re-route>
```

Each field is mandatory. If a field is "none" or "n/a", say so explicitly — silence is not the same as confirmed empty.

## Pattern: Refactor Split

Use when a single refactor touches many files but the change can be staged. Each task should leave the build green.

```markdown
### Task 1: Extract <Type> interface
- Objective: Introduce a behavior-preserving interface for <Type>.
- Scope: Add the interface; do not change call sites yet.
- Files: src/foo/types.rs (new symbol), src/foo/mod.rs (re-export)
- Invariants: All existing tests pass; no public API removed.
- Verification: `cargo test -p foo` and `cargo check --all-targets`.
- Blocked-by: none
- Blocks: Task 2

### Task 2: Migrate <module> to interface
- Objective: Replace direct <Type> references with the interface in <module>.
- Scope: src/foo/bar/*.rs only.
- Files: src/foo/bar/handler.rs, src/foo/bar/service.rs
- Invariants: Identical observable behavior; no test changes.
- Verification: `cargo test -p foo` plus targeted `cargo test bar::`.
- Blocked-by: Task 1
- Blocks: Task 3

### Task 3: Remove the legacy <Type> path
- Objective: Drop the unused direct path now that all callers use the interface.
- Scope: deletion only.
- Files: src/foo/legacy.rs (delete), src/foo/mod.rs (remove re-export)
- Invariants: Build green; no public consumer regressions.
- Verification: `cargo build --all` and `rg "<Type>::legacy_" src/`.
- Blocked-by: Task 2
- Blocks: none
```

## Pattern: Bug Repair

Three tasks: reproduce, repair, regression-guard. Reproduction precedes repair so the fix is provable.

```markdown
### Task 1: Reproduce <bug summary>
- Objective: Add a failing test that demonstrates the bug.
- Scope: test code only; no production change.
- Files: tests/regression/<area>.test.ts (new)
- Invariants: New test fails for the documented reason; existing tests still pass.
- Verification: `pnpm test tests/regression/<area>.test.ts` — expect failure with <message>.
- Blocked-by: none
- Blocks: Task 2

### Task 2: Repair <root cause>
- Objective: Fix the root cause identified in Task 1.
- Scope: minimal change in the affected module.
- Files: src/<area>/<file>.ts
- Invariants: Public API unchanged; failing test now passes.
- Verification: `pnpm test` (full suite green).
- Blocked-by: Task 1
- Blocks: Task 3

### Task 3: Add regression guard / docs
- Objective: Lock the fix in with explanatory comment and any related coverage.
- Scope: comments, additional asserts, or a sibling test only.
- Files: tests/regression/<area>.test.ts, src/<area>/<file>.ts
- Invariants: No behavior change beyond Task 2.
- Verification: `pnpm test` and `pnpm lint`.
- Blocked-by: Task 2
- Blocks: none
```

## Pattern: Migration Slice

Use for incremental migrations where each slice ships independently and the system tolerates a mixed state.

```markdown
### Task N: Migrate <subsystem> to <new pattern>
- Objective: Move <subsystem> from <old> to <new> behind <flag-or-shim>.
- Scope: <subsystem> directory only; do not touch consumers in this slice.
- Files: src/<subsystem>/* and config/<flag>.yaml
- Invariants: Old path still works; flag default unchanged.
- Verification: `pnpm test --filter <subsystem>` plus a targeted smoke test toggling the flag both ways.
- Blocked-by: <previous slice>
- Blocks: <next slice>
- Redirect signals: shared types changed during the slice -> stop and reconvene plan-creating.
```

## Pattern: Spike-Then-Execute

Use when ambiguity demands a discovery pass before commitment. The spike is read-only; the execute task is gated on the spike's findings.

```markdown
### Task 1: Spike — characterize <unknown>
- Objective: Produce a short note answering <specific questions>.
- Scope: read-only; no code changes.
- Files: notes/<topic>-spike.md (new)
- Invariants: No production files touched.
- Verification: Note exists, answers each question, and lists residual risks.
- Blocked-by: none
- Blocks: Task 2

### Task 2: Execute — implement <decision>
- Objective: Implement the chosen approach from Task 1.
- Scope: as bounded by the spike note.
- Files: <files identified in Task 1>
- Invariants: <invariants identified in Task 1>
- Verification: <verification identified in Task 1>
- Blocked-by: Task 1
- Blocks: none
- Redirect signals: spike findings invalidate the plan -> hand back to plan-creating.
```

## Pattern: Characterization Tests (Legacy Code)

Use before refactoring untested legacy code. Each task pins down behavior so later refactors are safe.

```markdown
### Task 1: Capture current behavior
- Objective: Add tests that document existing observable behavior, including quirks.
- Scope: tests only; no production change.
- Files: tests/characterization/<module>.test.ts (new)
- Invariants: Tests pass against current code, including known oddities.
- Verification: `pnpm test tests/characterization/<module>.test.ts`.
- Blocked-by: none
- Blocks: Task 2

### Task 2: Refactor under green tests
- Objective: Restructure <module> while characterization tests stay green.
- Scope: src/<module>/* only.
- Files: src/<module>/*.ts
- Invariants: Characterization tests pass at every commit.
- Verification: `pnpm test` plus targeted `pnpm test tests/characterization/<module>.test.ts`.
- Blocked-by: Task 1
- Blocks: none
- Redirect signals: a characterization test starts failing in a way the user didn't expect -> stop, surface the divergence to the user before continuing.
```

## Anti-Patterns

Reject task lists that include any of the following:

- **Vague verbs.** "Improve X", "clean up Y", "look at Z". Replace with a measurable objective.
- **Verification by vibes.** "Make sure it works." Replace with a concrete command or check.
- **Free-floating files.** A task whose Files list is `TBD` is not ready to dispatch.
- **Hidden coupling.** Two tasks that must land together without the dependency being declared.
- **Task inflation.** Splitting one obvious change into three "phases" to look thorough.
- **Verification skipped on cleanup tasks.** Deletion tasks still need `cargo build` / `pnpm build` / equivalent.

## Naming

- Use imperative titles: "Extract X", "Migrate Y", "Repair Z".
- Prefer present tense and active voice.
- Avoid status words in titles ("WIP:", "TODO:") — those belong in tracking, not the brief.
