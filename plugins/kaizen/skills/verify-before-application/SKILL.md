---
name: verify-before-application
description: Before applying ANY in-flow change (Boy-Scout finding, audit fix, refactor step, plugin edit, schema migration, structural relocation), prove the change is needed (RED) and verify the change is safe (GREEN). Test-driven discipline applied to every artifact, not just code. Triggers on phrases like "before I apply", "before I commit", "verify this change", "is this needed", "is this safe", and as the gate every other applying-class skill calls. Iron-Law skill — read in full.
metadata:
  version: 1.0.0
---

# Verify Before Application

The gate that prevents speculative changes from landing and forgotten findings from rotting.

## ⚠ Iron Law — read in full

This skill body MUST be read end-to-end before applying any section. The RED-GREEN structure is meaningless without the integration rules and the failure-mode catalog. Skipping to the matrix turns the skill into "I'll check the compiler after," which is exactly the failure mode the skill exists to prevent.

## Principle

Every applied change to the workspace clears two gates, in order:

1. **RED — proof of need.** Concrete evidence the change is grounded.
2. **GREEN — proof of safety.** Concrete verification the change works and breaks nothing.

Application happens **between** the two gates. If RED fails, the change isn't needed — discard it. If GREEN fails, the change isn't safe — fix or revert. Neither gate is optional.

## Why This Exists

Without this discipline, two failure modes dominate:

- **Speculative changes.** Application without RED proof. The change might be unnecessary (YAGNI violation), might introduce abstraction nobody asked for, might be a "looks better" with no measurable improvement. The codebase grows weight without gaining function.
- **Unverified changes.** Application without GREEN check. The change compiles in isolation but breaks an obscure call site, fails a regression test, or violates a structural rule. Trees pass, forest doesn't. Hidden breakage ships.

The verify-before-application gate makes both impossible: nothing applies without grounded need; nothing stays without verified effect.

## RED — Prove the change is needed

For each candidate change, produce concrete evidence **before writing the change**:

| Change class | RED evidence |
|---|---|
| Boy-Scout cleanup | grep result, call-site count (≥2), compiler/linter warning |
| Bug fix | failing test, reproduction script, error log entry |
| Refactor (DRY extraction) | duplication count (≥2 occurrences), grep diff |
| Refactor (relocation) | layer-violation grep, audit finding citation |
| New abstraction | ≥2 existing consumers (no abstractions for hypothetical future) |
| New port / trait | call sites for the operation across the planned consumers |
| Plugin edit | failing validator, broken behaviour, user correction quote |
| Schema migration | failing migration script, drift between source and cache |
| Dependency change | CVE, deprecation warning, version pin requirement |
| Documentation change | user confusion quote, missing/incorrect section identified |

If you cannot produce RED evidence, **DO NOT apply**. Mark the candidate as speculative; revisit when evidence emerges. "I'm pretty sure" is not RED. "I checked and N consumers do X, here is the grep output" is RED.

### RED for user-requested work

User intent does not waive RED. When the user requests a change, RED is "the user asked + the grep / call-site count / file structure that confirms the requested scope is real." If the requested change has no measurable surface (e.g. "refactor this nonexistent function"), surface that gap before applying.

## GREEN — Prove the change is safe

After applying, the project's verification surface runs cleanly. Pick the relevant surfaces for the change class:

| Verification surface | Required when |
|---|---|
| Compile barrier (`cargo check`, `tsc --noEmit`, `go build`, `ruff check`) | Every code change |
| Focused test suite (touched files) | Every code change |
| Broad test suite (full project) | Phase exit, before commit |
| Structural lint (ast-grep, import-linter, ArchUnit) | Every layer / topology change |
| Grep verification (forbidden imports, leaked symbols) | Every architectural change |
| Dep-graph check (cargo tree, go list, npm ls) | Every Cargo.toml / package.json / go.mod change |
| Plugin validator | Every kaizen plugin edit |
| Existing-suite regression (no tests touched) | Every pure relocation |
| Schema validator | Every schema migration |
| Smoke test (manual interaction) | Every UI / CLI / external-protocol change |

If GREEN fails, three valid responses, in order:

1. **Fix the regression** if the fix is small, grounded, and inside the change's scope.
2. **Revert the change** if the failure shows the change was wrong.
3. **Investigate** if the failure is novel. Do not paper over with `#[allow]` / `--no-verify` / mock data / commented-out assertion.

## TDD as the kernel

verify-before-application generalises TDD's RED-GREEN-REFACTOR cycle from "tests of behaviour" to "verifications of any artifact":

| TDD step | verify-before-application step |
|---|---|
| RED = failing test | RED = grounded evidence the change is needed (a failing test is *one* form of evidence) |
| GREEN = test passes | GREEN = all relevant verifications pass after application |
| REFACTOR = clean without breaking tests | REFACTOR = boy-scout cleanups during the same flow, each its own RED-GREEN cycle |

If you already practice TDD on code, this skill is the same discipline applied to: plugin edits, schema migrations, refactor relocations, architectural changes, configuration changes, docs cleanups, agent prompts, slash-command definitions, hook scripts, indexer schemas.

Pair with **tdd** for code-behaviour changes (where the test IS the RED evidence). This skill subsumes TDD when the artifact is non-code.

## Discovery-time integration

verify-before-application is the gate every applying-class skill calls. The same skill, invoked at the same point in each flow:

| Calling skill | Where the gate fires |
|---|---|
| **boy-scout-rule** | Rule 6 — every in-flow Boy-Scout finding |
| **audit** | Step 7 — every in-scope finding surfaced during the audit |
| **review** | Per cleanup applied alongside the review |
| **refactor** | Per task in the refactor plan |
| **onion-ddd-workflow** | Part 3 step ⓹ — per architectural change |
| **tdd** | Per RED-GREEN cycle (the gate IS the discipline here) |
| **executing-plans** | Per-task verification |
| **plugin-development** | Every kaizen plugin edit |
| **workflow** routines | Every "apply" stage |

When in doubt, the gate runs.

## Anti-Patterns

| Pattern | Why it's wrong |
|---|---|
| "It compiles, ship it." | Compile is one GREEN surface. Structural lints, regression tests, grep verifications might still fail. Run the surfaces that match the change class. |
| "I know this is needed, skipping RED." | The skip is exactly when YAGNI violations land. Make the evidence explicit even when it feels obvious — "obvious to me right now" is not the same as "grounded for the codebase." |
| "Apply, then verify, then revert if broken." | Works, but wastes cycles. RED-before-apply catches most "this is unnecessary" cases before you write a line. The forward-then-rollback pattern is the failure mode of skipping RED. |
| "The user asked me to do it, RED isn't needed." | RED for user-requested work is "the user asked + here's the existing call-site / grep / file structure that confirms scope." User intent doesn't waive evidence. |
| "Tests pass, so GREEN." | Tests are one surface. Structural changes need structural verifications (boundary lint, dep-graph, grep), not just behaviour tests. |
| Ending a discovery flow with "want me to apply X?" when X would pass RED+GREEN | This is the failure mode boy-scout-rule Rule 5 + this skill exist to prevent. Apply, don't ask. Asking permission to do work that's already been authorised by a passed gate is how findings rot. |
| Disabling a failing GREEN check (`#[allow]`, `// eslint-disable`, `--no-verify`) to ship | The check is the gate. Disabling the check is not the same as passing it. Either the check is wrong (fix the check) or the change is wrong (revert / re-do). |
| RED evidence pulled from cache / memory instead of fresh run | Evidence rots. Grep what's in the tree NOW, not what you remember from last session. Memory recall is not RED. |

## Discovery-Time Application Protocol

The canonical end-to-end flow for any "I just discovered something" situation:

```
discover → RED check → apply (only if RED passes) → GREEN check → report (what was applied + what was demoted, with the failing gate-check named for each demoted item)
```

The "report" step lists:
- **Applied:** what landed, with the GREEN check that proved it.
- **Trailed (deferred):** what was demoted, with the failing RED or GREEN check that caused the demotion.

**The report never lists "want me to apply X" for items that would have passed both gates.** That item belongs in "Applied".

## What this skill does NOT cover

- **The discipline of writing tests well** — that's `tdd` / `test-driven-development`. This skill assumes the test is one valid form of RED/GREEN evidence; it doesn't teach test design.
- **Architectural verification specifics** — that's `onion-ddd-workflow` Part 3. This skill provides the gate; onion-ddd-workflow provides the architectural-specific RED/GREEN commands (leaf-purity grep, dep-graph diff, port-uniqueness check).
- **What counts as a Boy-Scout finding** — that's `boy-scout-rule`. This skill provides the gate; boy-scout-rule provides the eligibility criteria.

## References

- `boy-scout-rule` — the eligibility skill this gate guards
- `tdd` / `test-driven-development` — the code-behaviour case of the same pattern
- `audit` — discovery flow that calls this gate per finding
- `review` — discovery flow that calls this gate per cleanup
- `refactor` — multi-step flow that calls this gate per task
- `onion-ddd-workflow` — architectural-specific instantiation of the GREEN matrix
- `executing-plans` — plan-driven flow that calls this gate per task
