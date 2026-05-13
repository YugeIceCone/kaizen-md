---
name: debugging-failures
description: Investigates failures to isolate root causes before editing code. Use when reproduction steps, logs, git state, or runtime evidence are needed and the cause is still unclear.
metadata:
  version: "1.1"
---

# Debugging Failures

Investigates failures to isolate root causes before editing code. Use this skill when something is failing and the root cause is not yet clear.

## Inputs

- the symptom or failing command
- expected behavior versus actual behavior
- any recent change that may have introduced the issue

## Debug Flow

1. Reproduce or narrow the failure.
2. Inspect the nearest evidence: tests, logs, tracebacks, configs, runtime state, and git diff.
3. Read the likely files and their callers.
4. Form the most defensible root-cause hypothesis.
5. Decide whether to continue into **fix**, **task**, or **create-plan**.

## Evidence Sources

- failing test output
- CLI or service logs
- stack traces and error messages
- recent local diffs or commits
- config or environment mismatches
- suspicious data or state in the project datastore

## Good Output Shape

- symptom
- evidence found
- likely root cause
- next action

## Companion Skills

- **fix** -> when the issue should be repaired after diagnosis
- **task** -> when the cause is already scoped to one code change
- **create-plan** -> when the repair needs multiple phases

## Agent Roles

Use the home agent catalog as role guidance:

- `bug-investigating` -> root-cause analysis and debugging

Use delegation only if the user explicitly asks for it.

## Rules

- Prefer evidence over intuition.
- Do not claim a root cause you cannot support.
- Stay read-only until the next action is clear unless the user explicitly wants the fix now.
- Avoid Markdown tables.
