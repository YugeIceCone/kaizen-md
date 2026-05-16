---
name: boy-scout-rule
description: When touching existing code and wanting to leave it better. Use when the user says "clean this up while I'm here," "should I fix this," "tech debt," "while I'm in this file," or "incremental improvement." Also use during ANY audit/review/refactor flow to apply in-scope findings inline rather than deferring them. Pairs with verify-before-execution (the RED-GREEN gate every Boy-Scout finding clears before applying). For full refactoring, see solid or separation-of-concerns.
metadata:
  version: 1.2.0
---

# Boy Scout Rule

## Before Applying

If `.agents/stack-context.md` exists, read it first. Apply this principle using idiomatic patterns for the detected stack. For framework-specific details, use context7 MCP or web search — don't guess.

## Principle

Leave every file you touch a little better than you found it. Not a lot better — a little better. Incremental improvement compounds into a clean codebase over time.

## Why This Matters in Production

Codebases don't rot overnight. They degrade one shortcut at a time — a hardcoded value here, a skipped rename there, a TODO that lives for three years. The Boy Scout Rule is the antidote: it makes improvement the default, not a scheduled event.

Teams that practice this never need "cleanup sprints." Their code stays healthy because maintenance happens continuously, embedded in regular feature work.

But this only works with discipline: improvements must be **small, safe, and scoped**. A "cleanup" that touches 40 files and breaks two features is worse than leaving the mess.

## Rules

1. **Fix what you see, within scope.** If you open a file to fix a bug and notice a misleading variable name, rename it. If you see a dead import, remove it. These are safe, low-risk improvements.
2. **Keep cleanups in separate commits.** A feature commit should contain the feature. A cleanup commit should contain the cleanup. Mixing them makes code review harder and reverts dangerous.
3. **Don't refactor what you don't understand.** If you open an unfamiliar file and something looks wrong, investigate before "fixing" it. What looks like dead code might be a critical fallback. What looks like a typo might be intentional.
4. **Scope your improvements.** Boy Scout Rule means fixing a confusing name or adding a missing type annotation. It does not mean redesigning a module you happened to walk past.
5. **Within-scope findings: apply in the same flow that found them.** If a finding meets the criteria in "What Counts as A Little Better" AND passes the verification gate (Rule 6) below, execute it before claiming the discovery work is done. Do not list in-scope findings as "suggested next steps," "future cleanup," "Boy-Scout next step," or "want me to apply that pass?" — that is how findings rot. Discoveries left to rot are forgotten.
6. **Verification gate — delegated to `verify-before-execution`.** Each in-flow finding clears the **verify-before-execution** RED-GREEN gate before landing:
   - **RED (proof of need)** — the improvement is grounded in real repeated patterns or a clear violation: grep, call-site count (≥2), compiler warning, failing test. No speculative cleanups.
   - **GREEN (proof of safety)** — the project's compile barrier and any covering tests pass after the change. Plus the boy-scout-specific bounds: scope ≤ ~20 LOC, single module, revert independent of the primary task.

   If RED fails, the finding wasn't real — discard. If GREEN fails, fix or revert. Demote to Rule 7 only when the finding is genuinely out of scope (not when you skipped the gate). See `verify-before-execution` for the full RED-GREEN matrix and integration rules.
7. **Out-of-scope findings: leave a trail.** If a finding fails the verification gate (too large, too speculative, cross-module, would change behavior), file it as a backlog item or `TODO(ticket-number)` with enough context to act on later. **"Leave a trail" is the fallback for items that genuinely cannot be done in passing — it is not the default for items you simply don't feel like doing.** Default to apply; demote to trail only on a failed gate check.

## What Counts as "A Little Better"

- Renaming a variable from `x` to `user_count`
- Removing an unused import or dead code
- Adding a missing type annotation
- Fixing a misleading comment (or removing a comment that restates the code)
- Replacing a magic number with a named constant
- Simplifying a conditional that's more complex than necessary
- Fixing a compiler/linter warning

## What Does NOT Count

- Rewriting a function in a "better" style without functional change
- Migrating to a new pattern across the whole codebase
- Adding features or changing behavior
- Reformatting files to match a different style (use autoformatters for this)
- Refactoring code that is unfamiliar to you without full understanding

## Boundaries

- **Size limit:** If a cleanup would touch more than ~20 lines or span multiple modules, it's not a Boy Scout improvement — it's a refactoring task that deserves its own ticket and review.
- **Tension with "don't touch what you don't own":** In shared codebases, small improvements are generally welcome. Large refactors across module boundaries require coordination. Know the difference.
- **Tension with minimal diffs:** Some teams prefer PRs that only contain the intended change. In that case, put Boy Scout cleanups in a separate PR.

## Discovery-Time Application Protocol

When boy-scout-rule fires during an audit, review, refactor, or extraction flow, the sequence is:

1. **Discover** the finding (grep, code-read, audit pass) and write it down in working memory.
2. **Run the Rule 6 verification gate** against the finding.
3. **Apply or trail.** If the gate passes, apply the change inline and re-run the compile barrier. If it fails any check, log it as a trail item (Rule 7) with the failing check named.
4. **Report what was done, not what was deferred.** The end-of-flow summary lists *applied* in-scope cleanups alongside the primary task. Any trail items are listed separately as deferred work, with the gate-check that demoted them.

**Anti-pattern to refuse:** ending a discovery flow with "Boy-Scout next step (not done — separate scope)" or "want me to apply that pass?" for findings that *would have passed the gate*. If the gate passes, the work belongs in this flow. Asking permission to do work that's already been authorized by the principle is how findings rot.

## Code Review Checklist

- [ ] Are the cleanups genuinely low-risk and obviously correct?
- [ ] Are cleanups in separate commits from feature work?
- [ ] Does the cleanup touch only code the author is actively working in?
- [ ] Would reverting the cleanup leave the feature intact?
- [ ] Were in-scope findings *applied during discovery* (Rule 5), not listed as "next steps"?
- [ ] For each deferred item, was the failing verification-gate check named (Rule 7)?

## Related Skills

- **verify-before-execution**: The RED-GREEN gate every in-flow finding clears (Rule 6). MUST load alongside this skill in any discovery flow that produces applicable findings.
- **kiss**: For identifying what "simpler" looks like
- **convention-over-configuration**: For knowing what the project's conventions are before "fixing" things
- **dry**: For spotting duplication worth consolidating
