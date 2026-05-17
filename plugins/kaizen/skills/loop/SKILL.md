---
name: loop
description: Runs tasks in self-correcting iteration loops where each pass builds on previous work. Use for autonomous refinement with automated verification.
metadata:
  version: "1.2"
---

# Task Looping

Runs a task in a self-correcting iteration loop where each pass sees previous work in files and git history and converges on a verifiable completion state.

The loop pattern:

1. The same prompt is fed to the agent each iteration.
2. The agent works on the task and modifies files.
3. A stop hook intercepts exit and feeds the prompt again.
4. The agent sees its previous work in files and git history.
5. The agent iterates until a completion promise is emitted or the iteration limit is reached.

## When To Use It

- tasks with clear automated verification (tests, linters, build checks)
- greenfield work that can be walked away from
- iterative refinement where each attempt builds on the previous
- tasks where the agent should self-correct based on its own output

## When Not To Use It

- tasks requiring human judgment at intermediate steps
- one-shot operations with no natural feedback signal
- tasks with unclear or subjective success criteria
- production debugging that requires targeted investigation

## Starting a Loop

See references/ralph-commands.md for the platform-specific commands.

Always set `--max-iterations` before starting. Never omit the safety limit.

## Writing Good Loop Prompts

A loop prompt must be self-contained. The agent cannot be prompted mid-loop.

Requirements:

- concrete objective with observable completion state
- automated verification step the agent can run itself (tests, build, lint)
- explicit completion signal: `Output <promise>PHRASE</promise> when done.`
- escape hatch: what to document or emit if the task is blocked after N iterations

Example:

```
Implement the cache invalidation logic in src/cache.ts.

Success criteria:
- unit tests in tests/cache.test.ts all pass
- no TypeScript errors
- no regressions in the full test suite

If all criteria pass, output: <promise>CACHE COMPLETE</promise>
If blocked after 15 iterations, document what prevented completion and output: <promise>BLOCKED</promise>
```

## Completion Promises

The stop hook uses exact string matching on the `<promise>` tag.

- emit `<promise>PHRASE</promise>` only when the stated condition is unequivocally true
- do not emit a false promise to escape the loop
- always set `--max-iterations` as the primary safety mechanism

## Iteration State

Between iterations the agent can observe:

- modified files from previous iterations
- git history showing what changed
- test output left on disk or logged

Write durable artifacts (files, notes, test reports) to preserve progress — do not rely on in-memory state across iterations.

## Companion Skills

- **task** -&gt; single-shot alternative when iteration is not needed
- **execute-plan** -&gt; phased alternative when sequencing matters more than repetition
- **tdd-implementing** -&gt; stricter red-green-refactor alternative for test-first work
- **guardrails** -&gt; gate check before starting a long autonomous loop
- **result-reflecting** -&gt; self-assessment within a single iteration pass

## Rules

- always set `--max-iterations` before starting a loop
- write durable state to files, not memory
- emit completion promises only when the criteria are fully met
- avoid Markdown tables
