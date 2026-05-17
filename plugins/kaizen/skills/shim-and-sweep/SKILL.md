---
name: shim-and-sweep
description: Use when carving up a god-crate, splitting a bounded context, renaming a public surface across many call sites, or any refactor on a codebase that must keep building between commits. Triggers on "carve out", "split this crate", "shim during refactor", "deferred deletion", "deletion manifest", "F-FINAL", "borg-loop refactor", "autopoietic refactor", "shim-and-sweep". Pairs with the kaizen pre_deletion_belief gate (no `git rm` mid-flight without authorization). Skill body MUST be read end-to-end before applying any phase.
metadata:
  version: "1.0"
  origin: shodan workspace borg-loop discipline (generalized 2026-05-13)
---

# Shim-and-Sweep — refactor without mid-flight breakage

The pattern: every relocation leaves a re-export **shim** at the old
path so consumers keep resolving. Shims accumulate in a **deletion
manifest**. A single explicitly-authorized commit at the end **sweeps**
all shims away. Concentrates deletion risk into one revertible
operation.

Originally proven in shodan's "borg-loop" refactor — a workspace that
literally refactors itself while running, so breaking imports mid-flight
would kill its own ability to continue. The pattern generalizes to any
large structural move.

## When to use this

- Splitting a crate / module into multiple smaller pieces
- Lifting a bounded context to a new location (Onion-DDD carve-out)
- Renaming a public surface across many call sites
- Any refactor where active processes / agents / integrations must
  keep working between every commit

## When to use something else

| Situation | Use |
|---|---|
| Small refactor (≤2 phases) | `refactor` schema |
| Behavior change | `build-feature` |
| Authorized dead-code delete | backlog item + `/kaizen:audit` |
| Pure file rename, no callers | `refactor` |

## Iron Laws

These are non-negotiable. Drift on any one and the discipline breaks.

1. **No mid-refactor `git rm`.** Every relocation leaves a 1-line
   re-export at the old path. The kaizen `pre_deletion_belief` gate
   enforces this automatically — if you stage a deletion, the commit
   is blocked.

2. **Compile + test green at every commit boundary.** The shim
   discipline is what makes this possible; combined with the
   characterization tests it makes phase-by-phase verification
   straightforward.

3. **Deletion manifest is authoritative.** Every shim's path is
   recorded in `.kaizen/workflow/deletion-manifest-<slug>.txt`.
   Nothing gets retired in the sweep that isn't in the manifest;
   nothing in the manifest survives the sweep (unless explicitly
   marked `KEEP`).

4. **F-FINAL (the sweep) is user-gated.** Either pre-authorized in
   the plan's `## Status` block or explicitly approved in
   conversation. `/loop` and similar autonomous drivers never fire
   the sweep on their own — see [[feedback_f_final_gate]].

5. **Pre-sweep safety tag** (`git tag pre-sweep-<slug>`) is created
   immediately before any `git rm` runs. Rollback is exactly
   `git reset --hard pre-sweep-<slug>`.

## The phases

The full ten-phase routine lives in
`schemas/shim-and-sweep/schema.yaml`. Run via:

```bash
/workflow schema=shim-and-sweep
```

Phase summary:

1. **explore** — file inventory + call-site grep + expected shim count
2. **analyze** — BEFORE / AFTER shape + scope tag + dep-direction
3. **characterize** — pin observable behavior (HARD GATE — same as
   `refactor`)
4. **create-plan** — phased plan + manifest skeleton + Status block
   declares F-FINAL gate state
5. **create-tasks** — one task brief per atomic carve
6. **carve-with-shim** — iterative body. Copy → shim → manifest →
   commit → architecture-log row. Repeat.
7. **migrate-callers** — redirect consumers off shim paths onto
   canonical paths
8. **drift-check** — grep verifies non-KEEP manifest entries have
   zero remaining consumers
9. **sweep** — single user-gated commit. `git tag pre-sweep-<slug>`
   then `git rm` everything in the manifest. Drop workspace deps.
10. **validate** — full suite + structural lints + characterization
    tests still green

## Shim shapes (per language)

The shim is a one-liner that re-exports the canonical content.
Anything more elaborate is a sign you're solving the wrong problem.

| Language | Shim |
|---|---|
| Rust | `pub use <new_path>::*;` (or specific symbols) |
| Python | `from <new_path> import *` (with `__all__` if needed) |
| TypeScript / JavaScript | `export * from "<new_path>";` |
| Go | type aliases (`type X = newpkg.X`) — no `export *` analog; explicit aliases per symbol |

If the shim is non-trivial — wrapping logic, parameter munging,
deprecation warnings — you have a 1.5-step migration, not a shim.
Split it: ship the canonical content first, then the wrapper as its
own commit with its own characterization tests.

## Manifest format

Plain-text append-only log at
`.kaizen/workflow/deletion-manifest-<slug>.txt`:

```text
# Deletion manifest — <plan-slug>
# Phase: <date carved> <path> [KEEP <reason>]
2026-05-10 crates/agent/src/borg_loop/state.rs
2026-05-10 crates/agent/src/borg_loop/primitives.rs
2026-05-11 crates/agent/src/serena/mod.rs  KEEP — public back-compat surface
2026-05-12 crates/agent/Cargo.toml
2026-05-12 workspace.dependencies::shodan-agent
```

The format is intentionally simple. `KEEP` entries survive the sweep;
everything else is retired.

## Pre-commit gate interaction

The kaizen pre-commit gate ships a `pre_deletion_belief` check
(`domain/git-discipline.yaml::no_deletion_without_auth`). It blocks
any commit that stages a deletion when matching brain-belief notes
exist (e.g. `~/.claude/.kaizen/brain/Notes/pref-no-deletions.md`). This is
**by design** — it forces the sweep phase to be explicit:

```bash
# during phases 1-8: gate fires correctly, blocks accidental rm
git commit              # ✗ blocked — "deletion staged + matching belief found"

# during phase 9 (sweep): explicit opt-in for one commit
KAIZEN_ALLOW_DELETE=1 git commit -m "<scope>-SWEEP — retire <N> shims"
```

Do NOT export `KAIZEN_ALLOW_DELETE=1` globally. Use it inline on the
single sweep commit only.

## Scope tags

The architecture-log row for each carve and for the sweep uses
shodan-style scope tags (per the project's `CLAUDE.md`):

- `§F1.x`, `§F-series` — file-set carve
- `§B0`, `§B-series` — bounded-context boundary
- `§M2`, `§M-series` — module re-org
- `<scope>-SWEEP` — the final sweep commit

Use whatever convention the project already follows; if none, default
to Conventional Commits prefixes (`refactor(scope)`, `refactor(scope)-SWEEP`).

## Composition with other skills

Load alongside:

- `kaizen:writing-plans` — Phase 4 plan structure
- `kaizen:executing-plans` — Phase 6 task-by-task discipline
- `kaizen:test-driven-development` — Phase 3 characterization
- `kaizen:boy-scout-rule` — Phase 6 incidental cleanups (without
  scope creep)
- `kaizen:onion-ddd-workflow` — when the carve also fixes a
  dependency-direction violation (then the shim doubles as a port
  lift)

## Anti-patterns to avoid

| Anti-pattern | Why it breaks |
|---|---|
| "Just delete and fix the callers" | Defeats compile-green-at-every-commit; one bad import paralyzes everyone |
| Skip the manifest, "I'll remember" | Memory is fallible; the sweep needs an authoritative list |
| Non-trivial shim (wraps logic) | Not a shim — split into two refactors |
| Sweep mid-refactor "while we're here" | Defeats deferred-deletion; loses the single-revert rollback |
| Set `KAIZEN_ALLOW_DELETE=1` globally | Bypasses the gate for unintended commits |
| Skip the safety tag before sweep | Rollback becomes per-file `git checkout` instead of one command |
| Use `/loop` to drive the sweep autonomously | F-FINAL is user-gated; autonomous loops are explicitly out of scope |

## Lookup pattern

When auditing a half-done refactor, find the in-progress shim-and-sweep
by checking:

```bash
ls .kaizen/workflow/deletion-manifest-*.txt
```

Each manifest file is one in-progress shim-and-sweep run; absence of
a manifest means no carve-out is in flight.

## See also

- `schemas/shim-and-sweep/schema.yaml` — full phase definitions
- [[feedback_no_deletion]] — the broader no-deletion discipline
- [[feedback_f_final_gate]] — F-FINAL never auto-fires under /loop
- `domain/git-discipline.yaml::no_deletion_without_auth` — gate
  enforcement
