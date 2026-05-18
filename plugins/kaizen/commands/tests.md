# /kaizen:tests

Run the kaizen plugin's test SUITE via the unified `kaizen-tests`
harness — auto-detects style per file (unittest / pytest / bash),
dispatches in parallel using all cores, surfaces slow dominators.

Distinct from `/kaizen:test` (which runs the TAP-style pipeline
smoke-test). This is the unittest+pytest+bash suite (~290 files).

## Usage

```
/kaizen:tests                          # full suite, parallel
/kaizen:tests --affected               # only tests for staged files
/kaizen:tests --pattern test_handoff*  # glob filter
/kaizen:tests --json                   # structured envelope
/kaizen:tests bench                    # per-file timing report
```

## Backing CLI

`kaizen-tests [--root R] [--tests-dir T] [--pattern P] [--concurrency N] [--affected] [--json] [bench [--top-n N]]`

See `skills/test-runner/SKILL.md` for the full design contract.
