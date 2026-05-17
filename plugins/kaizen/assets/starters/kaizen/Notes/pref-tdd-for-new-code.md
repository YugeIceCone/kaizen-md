---
name: Brand new code uses TDD
description: Net-new components land RED→GREEN→REFACTOR — tests first
created: {{today}}
updated: {{today}}
type: belief
confidence: 0.9
tags: [preference, workflow, tdd]
sources_count: 1
freshness: fresh
---

# Brand new code uses TDD

For any **net-new** component (new module, new trait, new type,
new function with non-trivial behavior), write the failing test
first. Watch it fail. Then implement the minimum to make it pass.
Refactor only when green.

## Why

Tests-after often becomes tests-never. Tests-first:
- Forces a clear contract before implementation
- Surfaces bad abstractions early (hard to test = hard to use)
- Provides regression coverage from day 1
- Documents intent better than comments

## How to apply

1. **Identify net-new boundary.** Is this a new entry point? New
   public function? New file? If yes → TDD.
2. **Write the test that DOESN'T exist yet.** It should fail because
   the code-under-test doesn't exist (or doesn't behave correctly).
3. **Run the test.** Confirm it's RED for the expected reason
   (not a syntax error).
4. **Implement the minimum.** Just enough to flip the test to GREEN.
5. **Refactor.** With a green safety net, restructure freely.

## When TDD is NOT the right tool

- One-off scripts you'll delete tomorrow
- Throwaway exploration / spike code
- Pure refactoring of code that ALREADY has tests
- Bug fixes — write a regression test, then fix (which IS TDD)

## kaizen integration

Invoke `/kaizen:tdd` to load the TDD skill body before starting
the work — the skill encodes the discipline + has language-specific
recipes (Rust `#[cfg(test)] mod tests`, Python `tests/`, TS
`*.test.ts` co-located).
