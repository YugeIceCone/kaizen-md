---
name: coverage
description: Mechanical 1:1 code-to-test mapper for the kaizen plugin. Use to check which workflow/scripts/*.py have matching tests/test_*.py and which don't. Triggers on "test coverage", "what's untested", "coverage gap", "1:1 ratio", "which scripts have no tests", "coverage report", "kaizen-coverage". Stdlib-only — no coverage.py / pytest-cov needed; this is structural mapping by filename convention, not runtime line coverage.
---

# kaizen coverage

Mechanical 1:1 code-to-test mapper. Walks the plugin's workflow
scripts and reports which have a matching test file and which don't.
The goal metric: **1:1** — every public script has at least one
test file pointing at it.

## What this skill IS

A structural / filename-convention mapping tool. Stdlib-only. Fast
(<100ms over the whole plugin). Answers: "which scripts have ZERO
tests written against them?"

## What this skill is NOT

- **Not runtime line coverage.** This doesn't run pytest, doesn't
  instrument the code, doesn't compute line/branch percentages.
  Use coverage.py / pytest-cov for that.
- **Not a test-quality judge.** A script that has `test_<x>.py`
  with one trivial test counts as "covered" here. The metric is
  *presence*, not *thoroughness*.
- **Not a replacement for `/kaizen:audit`.** Audit reports an
  aggregate test-file ratio across the whole tree; this tool zooms
  in on plugin scripts specifically and names the gaps.

## When to use

- Before claiming a feature is "done" — check `kaizen-coverage gaps`
  surfaces no new entries.
- Pre-commit / CI gate — `kaizen-coverage gaps` exits 1 when
  uncovered scripts exist.
- Onboarding — `kaizen-coverage report` is a fast "which features
  are battle-tested vs greenfield" tour.

## CLI

```bash
kaizen-coverage summary          # one-line ratio
kaizen-coverage summary --json   # machine-readable
kaizen-coverage gaps             # uncovered scripts, one per line (exit 1 if any)
kaizen-coverage gaps --json      # {"uncovered": [...]}
kaizen-coverage report           # ✓/✗ per script
kaizen-coverage report --json    # {"summary": {...}, "scripts": [{...}]}
```

## Coverage rules

A source `<name>.py` (under `scripts/<cluster>/`) is covered
when ANY of these test files exists in `tests/`:

1. `test_<name>.py` (exact match)
2. `test_<name>_*.py` (variants — e.g. `test_build_index_lazy.py` covers `build_index.py`)
3. `test_<head>*.py` where `head = <name>.split("_")[0]`
   (parent-feature tests exercise op scripts indirectly; e.g.
   `test_brain.py` counts as coverage for `brain_audit.py` too)

## What's excluded from the denominator

- `_<x>.py` — private helpers. They're tested via the public scripts
  that consume them.
- `<x>_mcp.py` — MCP servers. They're tested via their parent
  feature's tests (and via the `test_*_mcp*.py` integration tests
  when those exist).

## Why structural (vs runtime) coverage

Three reasons:

1. **No deps.** Stdlib-only — runs anywhere, no `uv` / `pip install`.
2. **Fast feedback.** <100ms over the whole plugin. Suitable for
   pre-commit and per-prompt invocation.
3. **Honest signal.** A script with zero test file is *definitely*
   untested. A script with a test file is at least someone's been
   thinking about it. The presence/absence delta is high-signal even
   without line-level instrumentation.

For runtime line coverage, layer pytest-cov on top — they answer
different questions.

## Output example

```
$ kaizen-coverage summary
kaizen-coverage: 69/77 scripts (89%); 8 uncovered

$ kaizen-coverage gaps
claude_docs_index
llm_proxy
models
observe
rules
trace
trace_index
trace_index_gpu

$ kaizen-coverage report --json | jq '.summary'
{
  "total":           77,
  "covered":         69,
  "uncovered_count": 8,
  "ratio_pct":       89
}
```

## Pairs with

- [`audit`](../audit/SKILL.md) — broader severity-classified audit
  (security / architecture / tech-debt / dependencies / coverage /
  docs / compliance). `audit` reports an aggregate ratio; `coverage`
  names the gaps.
- [`tdd`](../tdd/SKILL.md) — when `coverage gaps` surfaces a new
  uncovered script, TDD is the right way to add the missing test.
- [`plugin-development`](../plugin-development/SKILL.md) — the
  canonical feature shape includes a tests slot; this tool enforces
  it.
