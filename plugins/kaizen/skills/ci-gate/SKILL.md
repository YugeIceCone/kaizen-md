---
name: ci-gate
description: Runs the CI-equivalent merge gate locally — the heavy, whole-repo checks that gate a merge (bash/python/json/SKILL.md validity, iron-laws codegen drift, the full unittest suite). Use before declaring a routine done, before pushing, or before opening a PR. Distinct from the pre-commit gate, which is staged-scoped and fast.
metadata:
  version: "1.0"
---

# CI Gate

Runs the **CI-equivalent merge gate** — the same checks
`.github/workflows/test.yml` runs — locally, before the work leaves
the machine.

## When to use

- At the end of a workflow routine, after `review` / `validate`,
  before `report`.
- Before `git push` or opening a PR.
- After a refactor that touched many files, to catch a regression the
  staged pre-commit gate could not see.

## ci-gate vs pre-commit

| | pre-commit gate | ci-gate |
|---|---|---|
| Scope | staged diff only | whole repo |
| Speed | fast (seconds) | slow (~20s — runs the full suite) |
| When | every commit | before merge / push / routine-done |

The pre-commit gate keeps each commit clean; ci-gate proves the whole
repo is mergeable.

## How to run

```
bash skills/workflow/scripts/ci-gate.sh              # full gate
bash skills/workflow/scripts/ci-gate.sh --syntax-only  # static checks only
```

Or `kaizen-ci-gate` / `kaizen-ci-gate` from the shell. Exit 0 = green;
non-zero = the first failing check (with the offending file). Bypass
with `KAIZEN_CI_GATE_DISABLE=1` only when the gate itself is broken —
never to get past a real failure.

## What it checks

`ci-gate.sh` is the SSOT for the CI check list (`test.yml` calls it):
shell `bash -n`, Python `ast.parse`, JSON manifest validity, SKILL.md
frontmatter, iron-laws codegen drift (`codegen.py --check`), and the
full `unittest` suite.
