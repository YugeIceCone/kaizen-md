# Agent-Reusable Plan Template

A plan that another agent can resume must be self-contained: every fact the executor needs lives in the file. Copy this template, fill in concrete values, do not leave any field as `TBD` when the plan is approved.

## Full Template

```markdown
# Plan: <topic>

## Metadata
- Created: 2026-04-26
- Owner: <user / team / "any agent">
- Last updated: 2026-04-26
- Status: pending | in-progress | complete | blocked
- Plan file: plans/2026-04-26-<topic>.md
- Related: <link to issue, PR, ADR, parent plan>

## Goal
<One paragraph. What does success look like, observable from outside the code? Why are we doing this?>

## Current State
<What exists today, named symbols and files. Include line numbers if useful. The next agent should not have to re-derive this.>

Example:
- Auth middleware lives in `src/middleware/auth.ts:12-87`.
- It reads sessions from Redis via `getSession()` at `src/lib/session.ts:34`.
- Three callers: `src/api/v1/users.ts`, `src/api/v1/orders.ts`, `src/api/internal/admin.ts`.

## Assumptions
- <e.g. The Redis session store will not be replaced during this plan.>
- <e.g. No new auth providers will be added.>

## Unknowns
- <e.g. Whether the legacy `X-Session-Id` header is still in use by any clients.>
- <Each unknown should have a planned resolution in an early phase.>

## Out Of Scope
- <e.g. Migrating other middleware.>
- <e.g. Performance optimization beyond keeping current p99.>

## Invariants
Contracts that must hold across **all** phases. Each phase's verification implicitly checks these.

- Test suite stays green at every phase boundary.
- Public API surface (`src/api/**/*.ts` exports) unchanged.
- No schema migrations.
- p99 request latency stays within 10% of baseline.

## Verification Commands
Exact, copy-pasteable commands the project uses. Phases reference these.

- Unit tests: `pnpm test`
- Targeted: `pnpm test path/to/file.test.ts`
- Typecheck: `pnpm tsc --noEmit`
- Lint: `pnpm lint`
- Build: `pnpm build`
- Smoke test: `pnpm dev && curl localhost:3000/healthz`

## Phases

### Phase 1: <imperative title>
- **Status**: pending
- **Objective**: <one sentence>
- **Files**: <concrete paths, not "the auth area">
- **Steps**:
  1. <ordered, atomic actions>
  2. ...
- **Verification**: <exact command from Verification Commands above>
- **Rollback**: <git revert <commit>, or feature flag flip, or migration down>
- **Handoff to next phase**: <branch name, artifact, flag state, schema version>
- **Risks**: <known risks specific to this phase>
- **Notes**: <free-form, append as the phase runs — last test output, partial diff, blocker reasons>

### Phase 2: ...
[repeat structure]

### Phase N: Final integration
- **Status**: pending
- **Objective**: Compose all phase outputs and verify end-to-end.
- **Verification**: full test suite + smoke test from Verification Commands.

## Resume Protocol

For an agent picking this up cold:

1. Read this file top to bottom.
2. Find the first phase whose `Status` is not `complete`.
3. Read the **Notes** field for the in-progress phase to recover any partial state.
4. Run the **Verification Commands** for the previous (complete) phase to confirm the assumed state holds.
5. If verification disagrees with the recorded statuses, **stop and surface the mismatch** — do not silently edit the plan.
6. If the in-progress phase has no Notes and the recorded state matches reality, restart that phase from step 1 of its Steps list.
7. Append progress to **Notes** as work proceeds; update **Status** at phase boundaries; bump **Last updated** when changing the plan.

## Status Legend
- `pending` — not started
- `in-progress` — actively being executed; Notes field reflects current attempt
- `complete` — verified per the phase's Verification command
- `blocked` — cannot proceed; Notes explains why and what would unblock
```

## Worked Example: Refactor Plan

```markdown
# Plan: Extract auth middleware behind interface

## Metadata
- Created: 2026-04-26
- Owner: any agent
- Last updated: 2026-04-26
- Status: in-progress
- Plan file: plans/2026-04-26-auth-iface.md

## Goal
Replace direct `auth.ts` imports with an `AuthGuard` interface so callers can be tested with mocks and so a future auth provider swap is a one-file change.

## Current State
- `src/middleware/auth.ts:12-87` exports a free function `requireAuth(req, res, next)`.
- 3 call sites import it directly: `src/api/v1/users.ts:5`, `src/api/v1/orders.ts:7`, `src/api/internal/admin.ts:9`.
- No tests for the middleware itself; integration tests cover behavior end-to-end at `tests/api/*.test.ts`.

## Assumptions
- Session store (Redis) is not changing during this plan.
- No new auth providers will be added.

## Unknowns
- Whether `requireAuth` is re-exported anywhere implicitly. Phase 1 answers this.

## Out Of Scope
- Switching auth providers.
- Adding new auth flows.
- Refactoring session storage.

## Invariants
- `pnpm test` green at every phase boundary.
- Public surface of `src/api/**` unchanged.
- No new dependencies.

## Verification Commands
- Targeted: `pnpm test src/middleware/auth.test.ts`
- Full: `pnpm test`
- Typecheck: `pnpm tsc --noEmit`
- Build: `pnpm build`

## Phases

### Phase 1: Confirm import surface
- **Status**: complete
- **Objective**: Enumerate every import path of `requireAuth`.
- **Files**: read-only across `src/`.
- **Steps**:
  1. `rg -n "requireAuth" src/`
  2. Update Current State with findings if anything new.
- **Verification**: `pnpm tsc --noEmit` (no edits).
- **Rollback**: n/a (read-only).
- **Handoff**: list of import paths recorded in Notes below.
- **Notes**: 3 imports as expected; no implicit re-exports. Confirmed 2026-04-26.

### Phase 2: Introduce AuthGuard interface
- **Status**: in-progress
- **Objective**: Add interface alongside existing function; do not change callers yet.
- **Files**: `src/middleware/auth.ts`, `src/middleware/auth.test.ts` (new).
- **Steps**:
  1. Add `export interface AuthGuard { check(req): Promise<User | null> }`.
  2. Add `defaultGuard` exported alongside the existing function.
  3. Add unit tests for `defaultGuard`.
- **Verification**: `pnpm test src/middleware/auth.test.ts` and `pnpm tsc --noEmit`.
- **Rollback**: `git revert <phase-2-commit>`.
- **Handoff**: `defaultGuard` exported; existing `requireAuth` still works.
- **Notes**: Tests written; one mock fixture extracted to `__fixtures__/session.ts`.

### Phase 3: Migrate callers
- **Status**: pending
- **Objective**: Replace direct imports with interface-injected callers.
- **Files**: `src/api/v1/users.ts`, `src/api/v1/orders.ts`, `src/api/internal/admin.ts`.
- **Steps**: 1. Inject `AuthGuard` per route. 2. Pass `defaultGuard` at composition root.
- **Verification**: `pnpm test`.
- **Rollback**: `git revert <phase-3-commit>` (Phase 2 still leaves a working interface).
- **Handoff**: all 3 callers use `AuthGuard`; `requireAuth` no longer imported in callers.

### Phase 4: Remove legacy export
- **Status**: pending
- **Objective**: Delete `requireAuth` from public exports.
- **Files**: `src/middleware/auth.ts`, `src/middleware/index.ts`.
- **Steps**: 1. Remove function. 2. Remove re-export.
- **Verification**: `pnpm test && pnpm build`.
- **Rollback**: `git revert <phase-4-commit>`.

## Resume Protocol
[as above — universal]

## Status Legend
[as above — universal]
```

## Anti-Patterns

A plan that fails the agent-reuse test usually has one of these:

- **Implicit context.** "Use the new auth pattern we discussed earlier." A fresh agent has no `earlier`. Spell it out.
- **Vague verification.** "Make sure auth still works." Use the actual command.
- **Files: the auth area.** Concrete paths only. If you don't know them yet, the plan isn't ready.
- **Open-ended phases.** "Phase 3: Refactor callers." Too vague — split or specify.
- **Missing rollback for risky phases.** A migration phase without a rollback note is a trap for the executor.
- **Status drift.** Statuses not updated as phases run. The next agent can't trust the file.
- **Notes used as scratch then deleted.** Notes accumulate state — they should grow, not shrink.
- **One giant phase.** If a phase's Steps list has 12 items, it should be two or three phases.
- **No invariants.** Without invariants the executor cannot tell if a phase silently broke something orthogonal.

## Sizing Heuristic

A phase should:

- be implementable in 30–90 minutes of focused work
- leave the build green
- be revertible by a single `git revert`
- have a verification command that runs in under 5 minutes

If a phase fails any of these, split it.

## Compatibility With tasks-creating

A phase that is too large for direct execution can be expanded in-place by **tasks-creating**. Append a `## Tasks` subsection inside the phase rather than creating a separate task file — keeps the plan self-contained.

```markdown
### Phase 3: Migrate callers
- **Status**: pending
- ... [phase fields]

#### Tasks
1. Migrate `src/api/v1/users.ts` (verification: `pnpm test src/api/v1/users.test.ts`)
2. Migrate `src/api/v1/orders.ts` (verification: `pnpm test src/api/v1/orders.test.ts`)
3. Migrate `src/api/internal/admin.ts` (verification: `pnpm test src/api/internal/admin.test.ts`)
```

## Compatibility With Subagents

When the plan will be handed to subagents:

- **Each phase is self-contained** so a subagent prompt can be: "Read plans/X.md, execute Phase N, do not touch other phases, return when verification passes."
- **Verification commands are listed once** so subagent prompts stay short.
- **Handoffs are explicit** so subagents pass artifacts correctly (branch names, flag state).
- **Resume Protocol** is the single source of truth — subagent prompts just point at it.
