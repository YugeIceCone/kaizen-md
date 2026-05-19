---
name: coverage
description: Mechanical 1:1 code-to-test mapper for the kaizen plugin. Walks `skills/workflow/scripts/*.py` (excluding `_<x>.py` private helpers + `<x>_mcp.py` MCP servers) and reports which scripts have a matching `tests/test_<x>*.py` and which don't. Stdlib only — no coverage.py / pytest-cov required. Subcommands - summary | gaps | report. Default behavior - emit `gaps` (the actionable one).
argument-hint: "summary | gaps | report [--json]"
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/bin/kaizen-coverage:*)"]
---

# kaizen coverage

Mechanical 1:1 code-to-test mapper. Goal: every public script has a
matching test file.

!`bash -c 'exec ${CLAUDE_PLUGIN_ROOT}/bin/kaizen-coverage ${ARGUMENTS:-report}'`

## Subcommands

- `summary [--json]` — one-line ratio + count (exit 0)
- `gaps [--json]` — list only uncovered scripts (exit 1 if any; for CI gating)
- `report [--json]` — full per-script breakdown (exit 0)

## Coverage rules

A source `<name>.py` is covered when ANY of these test files exists:

- `tests/test_<name>.py` (exact)
- `tests/test_<name>_*.py` (variants, e.g. `test_build_index.py` covers `build_index.py`)
- `tests/test_<head>*.py` where `head = <name>.split('_')[0]`
  (parent-feature tests exercise op scripts indirectly)

Excluded from the denominator: `_<x>.py` private helpers (tested via
consumers) + `<x>_mcp.py` MCP servers (tested via parent feature).
