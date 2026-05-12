---
name: vibe-check
description: AI-assisted-coding discipline checklist. Use BEFORE accepting AI-generated code, BEFORE staging AI-authored changes, and as a periodic audit against "vibe-coding" anti-patterns. Triggers on "vibe coding", "AI code review", "before I commit this AI thing", "is this AI-generated code safe", "vibe check", "AI-authored PR". Encapsulates the Presta checklist (wearepresta.com/vibe-coding-tips-checklist-avoid-breaking-builds) plus kaizen's own gate-integration recipe.
---

# Vibe-check — AI-coding discipline

You (the agent) are about to commit AI-generated or AI-assisted code. This skill is the discipline gate. Apply BEFORE staging anything. The user has explicitly opted into this skill — they want the heavy review.

## Core principle (Presta source, paraphrased)

> Treat AI output as **draft code**, not final code. Equivalent safety scrutiny to human contributions. Speed of vibe-coding only becomes predictable delivery when the discipline is institutionalized.

## Pre-commit checklist (mandatory)

Run each step. Surface results to the user. Block commit on any failure.

1. **Intent + placement confirmed**: state in one sentence what the change is for and why this file/module is the right home. If you can't, the change isn't scoped yet — stop and clarify.
2. **Static analysis green**: project's lint/format command exits 0. For Rust: `cargo check --workspace` + `cargo clippy`. For TS: `tsc --noEmit` + `eslint`. For Python: `ruff check` + `mypy` if present. (`kaizen:gate` Check #1 already runs this if `compile_check_cmd` is set.)
3. **Tests cover new code paths**: for every new `pub fn` / exported function, a corresponding test exists OR a deliberate `KAIZEN_SKIP_TDD_CHECK=1` justification is in scope. Check via `kaizen:gate` Check #7 (paired-test).
4. **Dependencies validated**: new `Cargo.toml` / `package.json` entries → version pinned, license known, brain `dependency-allowlist` rule consulted if present.
5. **CI gate dry-run passes**: `/kaizen:gate` reports green or only-warnings. Red → fix before committing.

## Anti-patterns to refuse (auto-block)

- **Blind acceptance**: pasting a snippet without a paired test or without running the compile barrier. ❌
- **Ignoring contracts**: generated code that changes a `pub trait` signature or `pub struct` field without updating all callers. ❌
- **Skipping dependency management**: a new `use foo::bar` import where `foo` isn't yet in `Cargo.toml`, or a `npm install` step omitted. ❌
- **Environment parity drift**: assuming a different OS / shell / runtime than the project's CI uses (e.g. macOS-only `readlink -f` in code that ships to Linux CI). ❌

Each maps to a `kaizen:plugin-pitfalls` entry. If you hit one, the skill body of the matching pitfall is the canonical fix.

## Safe prompt patterns (use when YOU are the prompter)

These are how to ASK for AI help so the response is safer:

- "Make the change in `<file>:<line-range>` only. Don't refactor surrounding code."
- "Return only the modified function + a unit test using `<test-framework>`."
- "Use the existing `<type>` rather than introducing a new abstraction."
- "If you need new deps, list them but don't add to Cargo.toml — I'll review."
- "Show the change as a unified diff against `<file>`."

These map to a hidden truth: **scope-limited prompts produce safer changes**. Open-ended "make this better" produces broad refactors that bypass review.

## Review checklist (when reviewing AI-origin code, yours or another agent's)

For each AI-generated change in the staged diff:

- ✅ Aligns with the stated product requirement (open the issue / spec; confirm)
- ✅ Tests cover normal + edge cases (not just the happy path)
- ✅ API contracts unchanged OR change is explicit + documented
- ✅ Dependency additions licensed acceptably + version-pinned
- ✅ Performance impact on hot paths considered (or N/A — say so)
- ✅ Error handling + logging present (no silent `try: ... except: pass`)
- ✅ Cross-check: the AI's EXPLANATION of what it did matches what the diff actually shows
- ✅ Small PR (≤15 files per kaizen sizing rule; bigger → split)

## Governance + traceability (Presta + kaizen integration)

When you commit AI-authored code:

- **Commit message marker**: prefix the Conventional Commits scope with `[AI]` or append `(AI-assisted)` to surface that an AI contributed.
  - Example: `feat(api)[AI]: add /v1/users endpoint with input validation`
- **Audit trail via trace**: kaizen-trace already captures every `UserPromptSubmit` event. The audit log is automatic. Query via `kaizen-trace query --src user --since 1h`.
- **Brain rule**: optional — declare a `dependency-allowlist` brain rule that the gate Check #14 enforces. Templates: `kaizen-rules template dependency-allowlist`.

## Gradual adoption (start small)

Per Presta's recommendation:

1. **Phase 1**: use vibe-coding ONLY on internal-tool / helper / docs changes. Block on customer-facing code.
2. **Phase 2**: when 5 consecutive vibe-coded commits pass `/kaizen:gate` cleanly without revert, expand scope to non-critical features.
3. **Phase 3**: customer-facing code allowed AFTER:
   - Test coverage > 80% on the touched module
   - At least 1 human reviewer approves
   - Performance regression tests pass

Measure: track via `kaizen-trace query --evt PostToolUse-bash --since 7d | grep "git commit"` to count AI-touched commits; correlate with revert rate.

## When to invoke this skill

- Before staging AI-generated code (you, an agent, or a paired-pilot session).
- When the user says "vibe check this" / "is this safe to commit" / "the AI wrote this — review it".
- Periodically as a discipline reminder when working in vibe-coding-heavy phases.

## What this skill ≠

- ≠ `kaizen:kaizen` (the git-workflow rulebook). This is upstream — applied BEFORE staging. Kaizen-gate is the enforcement layer.
- ≠ `kaizen:tdd` (test-first discipline for net-new). This is the discipline AFTER an AI produces a draft; tdd is for new code you write deliberately.
- ≠ a replacement for code review. It's the agent's self-review pass that precedes human review.

## Related skills

- `kaizen:kaizen` — the gate that enforces the checklist
- `kaizen:plugin-pitfalls` — concrete anti-pattern catalogue
- `kaizen:behaviour-config` — how to author brain rules (incl. `dependency-allowlist`)
- `kaizen:writing-plans` — when a vibe-coded change grows beyond micro size
- `coding-skills:kiss` + `:yagni` — the "stop over-engineering" principles vibe-coding tends to violate

## Iron Laws (non-negotiable)

1. **No commit without a paired test** for new exported functions, unless an explicit `KAIZEN_SKIP_TDD_CHECK=1` justification is in scope.
2. **No new dependencies without inspection** — read the README, check the license, pin the version.
3. **No bypassing the gate** — `git commit --no-verify` is only for true emergencies and must be followed by an immediate fix-up commit with the gate passing.
4. **AI explanations must match the diff** — if the AI said "I added X" and the diff shows Y, reject and re-prompt.
5. **Small changes** — sized via grep/cargo-tree/ast-grep, NEVER by clock-time (per kaizen's `pref-sizing-by-trace-not-hours`).
