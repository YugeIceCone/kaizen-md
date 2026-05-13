# Plan Execution Protocol

Operational details for executing an agent-reusable plan. The plan file itself is the authoritative state — these patterns describe how to keep that state honest across sessions and subagents.

## Resume Protocol (executor side)

The plan's own Resume Protocol section is the entry point. As the executor:

1. Open the plan file from its `Plan file` path in Metadata.
2. Read every section, in order, even if you wrote the plan yourself in a previous session — context decays.
3. Find the first phase whose `Status` is not `complete`.
4. If that phase is `in-progress`:
   - Read its **Notes**. The previous executor (you, a subagent, a prior session) recorded what was tried.
   - Run the previous (`complete`) phase's Verification command. If it now fails, the plan is out of sync with reality — stop and report.
   - If verification passes and Notes show partial progress, decide: continue from where Notes left off, or restart the phase from step 1 of its Steps. Continuing is faster but needs trust in the Notes.
5. If that phase is `pending`, start it from step 1.
6. If that phase is `blocked`, do not skip it — read the Notes and surface the blocker before doing anything else.

Never silently change a phase's Status from `blocked` to `pending` to "try again" — surface the unblock first.

## Status Transitions

```
pending → in-progress → complete
                    ↘ blocked → in-progress (after explicit unblock)
```

Allowed transitions only. `complete → in-progress` is **not** allowed — re-opening a complete phase means a regression was found in a later phase, and the proper response is to add a new fix-up phase rather than rewrite history.

## Per-Phase Update Protocol

When entering a phase:

```markdown
### Phase 2: Introduce AuthGuard interface
- **Status**: in-progress  ← updated from `pending`
- **Notes**: 2026-04-26 21:14 starting; reading src/middleware/auth.ts.
```

While running:

```markdown
- **Notes**: 
  - 2026-04-26 21:14 starting; reading src/middleware/auth.ts.
  - 2026-04-26 21:22 added AuthGuard interface; tests not yet written.
  - 2026-04-26 21:28 unit tests pass: `pnpm test src/middleware/auth.test.ts` ✓
```

On completion:

```markdown
- **Status**: complete  ← updated from `in-progress`
- **Notes**: 
  - ... (history above)
  - 2026-04-26 21:30 verified `pnpm test src/middleware/auth.test.ts` ✓ (commit def5678)
```

On block:

```markdown
- **Status**: blocked
- **Notes**:
  - ... (history above)
  - 2026-04-26 21:35 BLOCKED: Phase depends on PR #1234 landing first (the legacy session API rename).
```

Bump `Last updated` in Metadata after every status change.

## Sub-Agent Dispatch Patterns

### Single-phase delegation

```
Task: Execute Phase N of plans/<file>.md.

1. Read plans/<file>.md top to bottom.
2. Follow its Resume Protocol.
3. Execute Phase N only — do not touch other phases.
4. Update Phase N Status and Notes in the plan file.
5. Stop and return when:
   - Phase N's Verification command passes (Status=complete), or
   - Phase N is blocked (Status=blocked with cause in Notes).
6. Do not invent phases, edit other phases' status, or change the plan structure.
```

### Parallel independent phases

When phases have no Blocked-by relationship (true parallelism), dispatch one subagent per phase using **dispatching-parallel-agents**. Each runs its own copy of the single-phase prompt above, against the same plan file.

Risks:

- **Concurrent writes to the plan file.** Each subagent updates its own phase's Status/Notes. Use one subagent per phase (no overlap) and have the parent reconcile after they all return.
- **Concurrent writes to source files.** If two phases touch the same file, they are not actually independent — the plan was wrong. Stop and route back to **plan-creating** to fix the dependency graph.

### Resume after subagent return

The parent agent (you) checks the plan file:

- All dispatched phases `complete`? Run integration verification.
- Any `blocked`? Read Notes, decide next step. Often the unblock is a new phase that goes between the blocked phase and the next phase.
- Any still `in-progress` because a subagent timed out? Surface to the user; do not silently re-dispatch.

## Mid-Plan Failure Recovery

A phase fails verification. Options:

1. **Self-contained failure** — bug in the phase's own change. Diagnose with **debugging-failures**, fix, re-verify, mark complete. Update Notes.

2. **Earlier phase regression** — a `complete` phase silently broke something this phase depends on. Do not edit the earlier phase's Status. Instead:
   - Add a fix-up phase between the broken `complete` phase and the current `in-progress` phase.
   - Document the regression in the new phase's Notes.
   - Mark the current phase `blocked` with a pointer to the new fix-up phase.
   - Run the fix-up phase, mark it complete, then resume the original phase.

3. **Plan invalidated** — a discovery during execution shows the plan's Assumptions are wrong. Stop. Mark current phase `blocked`, record the discovery in Notes. Route to **plan-creating** for a plan amendment. Do not silently rewrite phases.

4. **Environmental flake** — flaky test, network blip. Capture with `git notes add` against the failing commit, retry once, record outcome in Notes. If still flaky, mark `blocked` and surface — do not retry-loop.

## Mismatch Handling

If the codebase no longer matches the plan's Current State or Assumptions:

1. State the mismatch in the affected phase's Notes:
   ```
   - 2026-04-26 21:40 MISMATCH: plan Current State says auth.ts:12-87 exports `requireAuth` 
     as free function, but it is now a class method on `AuthMiddleware`. Likely changed by 
     PR #1240. Intent of this phase still applies; updating step 1 to use the class method.
   ```
2. Decide if intent holds. If yes, edit the affected phase (not earlier phases) to match reality, bump `Last updated` in Metadata, continue.
3. If no, mark the phase `blocked`, route to **plan-creating** for a plan amendment.

Never silently rewrite the plan to look like it was always right. The audit trail matters.

## Integration Verification (post-plan)

After the last phase is `complete`:

- Run the full test suite from Verification Commands.
- Run the project's compile barrier (`pnpm tsc --noEmit`, `cargo check`, `tldr diagnostics .`).
- Run a smoke test that touches the user-visible behavior the plan changed.
- Run lint if it is a CI gate.

If any of these fail, the phases composed badly. Do not retroactively edit phase statuses — open a new fix-up phase, document in its Notes, run it, then mark the plan complete.

When everything passes, set the plan's top-level Metadata Status to `complete` and bump `Last updated`.

## Reporting Done

Final report includes:

- ✅ phases completed, with verification command and commit / diff link
- ⚠ phases completed with caveats (flake, scope adjustment), with link to git note
- ❌ phases blocked or rolled back, with cause
- integration verification result
- follow-ups the user should know about (cleanups, removed feature flags, etc.)

A two-paragraph summary that says "X done, Y deferred because Z" is more useful than a green tick on incomplete work.

## Anti-Patterns

- **Skipping the Resume Protocol.** Diving into "the next phase" without reading Goal, Invariants, and prior Notes — leads to drift.
- **Silent status updates.** Editing the plan file mid-edit-burst without saving — the next agent sees stale state.
- **Retroactive status rewrites.** Marking a phase `complete` after the fact when its Verification command was not actually run.
- **Plan-as-scratchpad.** Treating the plan as your working notes; the plan is the agent-shared source of truth and must stay coherent.
- **Eager subagent fan-out.** Dispatching parallel subagents for phases with implicit shared state — they collide on the plan file or source files.
- **Verification by vibes.** "Should be fine, the diff is small." Always run the phase's declared Verification command.
- **Skipping integration check.** Per-phase green is necessary, not sufficient.
- **Bypassing block.** Flipping `blocked → pending` without resolving the cause documented in Notes.

## Quick Reference: Common Verification Commands

The plan should already list these. If it does not, route back to **plan-creating** to add them — do not invent your own.

- TypeScript / pnpm: `pnpm test`, `pnpm tsc --noEmit`, `pnpm build`, `pnpm lint`
- Rust / Cargo: `cargo test`, `cargo check --all-targets`, `cargo build --all`, `cargo clippy --all`
- Python: `pytest`, `mypy .`, `ruff check .`, `python -m compileall .`
- Project-specific: `tldr diagnostics .`, `make check`, `bun test`, etc.

## When To Stop And Hand Back

Stop the execution and route back to **plan-creating** if any of these are true:

- the plan is missing Verification Commands, per-phase Status, or Resume Protocol
- the dependency graph between phases is unclear or appears cyclic
- discovery during execution invalidates the plan's Assumptions
- the user changes acceptance criteria mid-execution
- two phases that the plan claims are independent are actually touching the same files

Do not absorb planning work silently — the next agent needs the corrected plan in writing.
