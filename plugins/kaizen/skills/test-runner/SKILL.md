---
name: test-runner
description: Unified test harness for the kaizen plugin. Subsumes the historical 5 entry points (unittest discover / pytest / run_tests_parallel / legacy _tests.py / bash test_plugin_root.sh) into one CLI `kaizen-tests` with auto-style detection (.py unittest.TestCase / .py bare-class or module-fn / .sh) and per-file parallel dispatch using all cores. Subcommands `bench` for per-file timing to find slow dominators, `--affected` for staged-files subset, `--json` for envelope output. Triggers on "run the tests", "run kaizen tests", "kaizen test", "kaizen-tests bench", "find slow tests", "test runner", "test harness", "unified test", "which tests are slow", "bench tests".
metadata:
  version: "1.0.0"
---

# kaizen-tests — unified test harness

One CLI to run the plugin's tests. Replaces:

| Was | Now |
|---|---|
| `python3 -m unittest discover -s tests` | `kaizen-tests` |
| `python3 -m pytest tests/test_X.py` | `kaizen-tests` (auto-detected) |
| `kaizen-run-tests-parallel --modules ...` | `kaizen-tests --affected` |
| `python3 _tests.py` (legacy) | `kaizen-tests` (folds in) |
| `bash test_plugin_root.sh` | `kaizen-tests` (auto-detected .sh) |

## CLI

```bash
kaizen-tests                          # full suite, parallel, auto-style
kaizen-tests --affected               # only tests for staged files
kaizen-tests --pattern test_handoff*  # glob filter on stems
kaizen-tests --concurrency N          # override (default: nproc)
kaizen-tests --json                   # structured envelope output
kaizen-tests bench [--top-n N]        # per-file timing report (slowest first)
```

## Style auto-detection (pure function)

`_tests_run.classify_style(path)` walks each file once:

- `.sh` extension → **bash** (`bash <path>`)
- File body contains `class X(unittest.TestCase)` → **unittest** (`python -m unittest tests.<stem>`)
- Bare `class TestX:` OR module-level `def test_x(...)` → **pytest** (`python -m pytest -q <path>`)
- Else (empty/placeholder) → **unittest** (graceful — unittest's rc=5 "0 tests" is handled)

Mixed-style suites work without any per-file flags. The 5 pytest-only files in the current suite dispatch correctly without the runtime fallback hack that `run_tests_parallel.py` previously needed.

## bench — find the dominators

In a fully-parallel run, wall time is bounded by the slowest single file. `kaizen-tests bench` surfaces those:

```
top 25 slowest of 287 files:
        34.22s  tests.test_learning_log    ← dominator
         7.27s  tests.test_ci_gate
         7.21s  tests.test_self_audit
         ...
  287 files, 286 passed, 1 failed, total 221.4s sequential ceiling
```

Anything >5s deserves a look — usually a subprocess-heavy seed loop (e.g. `test_learning_log::test_append_cost_constant` makes 1,001 subprocess calls to seed the log; could be 10× faster with direct file-write seeding).

## Concurrency

Default = `os.cpu_count()` (full nproc — confirmed working at 32 cores).
Override via `--concurrency N` or `KAIZEN_TEST_CONCURRENCY=N` env.

## Design contract

- **PROGRAMMABLE** — pure helpers in `_tests_run.py` (classify / dispatch / report)
- **REPRODUCIBLE** — same `(files, concurrency)` → same pass/fail breakdown
- **CONSISTENT** — `--json` everywhere; exit 0 on pass; 1 on any failure
- **DETERMINISTIC** — no randomness; ordering is asyncio.gather (stable)
- **REUSABLE** — add a new style by extending the 3 pure functions

## File layout (canonical 9-slot)

```
skills/test-runner/SKILL.md                    — this file
skills/workflow/scripts/_tests_run.py        — pure core (classify/dispatch/report)
skills/workflow/scripts/tests_run.py         — CLI (asyncio + argparse)
bin/kaizen-tests                                — wrapper
commands/test.md                               — slash command
plugin.json::permissions.allow                 — 2 entries
tests/test_tests_run.py                      — 15 paired tests
```

## Migration from `run_tests_parallel.py`

The older `run_tests_parallel.py` stays in-place for back-compat (gate's `affected-tests` check still calls it). Phase 2 (separate commit) will migrate the gate to call `kaizen-tests --affected --json`.

## What this does NOT do (YAGNI)

- No coverage measurement (use `kaizen-coverage` for 1:1 script↔test mapping)
- No watch mode (out of scope; use `entr` / `fswatch` if needed)
- No per-test (sub-file) timing (file-level is enough to find dominators)
- No retry-on-flake (a flaky test is a real bug — fix at source)
