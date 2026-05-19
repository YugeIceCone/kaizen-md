---
name: test-suite
description: Run the kaizen plugin's unittest+pytest+bash test SUITE via the unified `kaizen-tests` harness — auto-detects style per file, dispatches in parallel, surfaces slow dominators. Distinct from `/kaizen:test` (TAP-style pipeline smoke). Renamed from `/kaizen:tests` 2026-05-19 to eliminate the singular/plural footgun. Subcommands - (none = full suite) | --affected | --pattern <glob> | --json | bench
argument-hint: "[--affected | --pattern <glob> | --json | bench [--top-n N]]"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-tests:*)"]
---

# /kaizen:test-suite

!`bash ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-tests $ARGUMENTS`

Run the kaizen plugin's test SUITE via the unified `kaizen-tests`
harness — auto-detects style per file (unittest / pytest / bash),
dispatches in parallel using all cores, surfaces slow dominators.

Distinct from `/kaizen:test` (which runs the TAP-style pipeline
smoke-test). This is the unittest+pytest+bash suite (~290 files).

## Usage

```
/kaizen:test-suite                          # full suite, parallel
/kaizen:test-suite --affected               # only tests for staged files
/kaizen:test-suite --pattern test_handoff*  # glob filter
/kaizen:test-suite --json                   # structured envelope
/kaizen:test-suite bench                    # per-file timing report
```

## Backing CLI

`kaizen-tests [--root R] [--tests-dir T] [--pattern P] [--concurrency N] [--affected] [--json] [bench [--top-n N]]`

See `skills/test-runner/SKILL.md` for the full design contract.
