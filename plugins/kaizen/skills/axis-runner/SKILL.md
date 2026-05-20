---
name: axis-runner
description: Declarative YAML-as-axis runner. Use to add a new coverage axis without writing a standalone Python file — declare it in `schemas/workflow/axes/<name>.yaml` with a scan_spec (grep / ast-rule / file-coverage) + verdict_rule, then run via `kaizen-axis-runner run --axis <name>`. Triggers on "new coverage axis", "declarative axis", "yaml axis", "subsume coverage script", "kaizen-axis-runner". The runner loads → validates against axis.schema.json (jsonschema graceful) → dispatches by scan_spec.type → emits canonical envelope.
---

# kaizen axis-runner

Declarative YAML-as-axis loader + dispatcher. Subsumes simple
standalone-Python coverage axes (one-line regex / single AST rule /
file-coverage pairing) by letting them be declared in YAML rather
than written as a new `.py` file.

## What this skill IS

A schema-driven runner with three composable dispatcher backends:

- **grep**          → line-by-line regex scan across a glob
- **ast-rule**      → named AST rule applied per Python file
- **file-coverage** → expected-glob ↔ actual-glob stem matching

Each axis YAML declares one scan_spec + a verdict_rule
(`green_max` / `yellow_max` thresholds). The runner emits the
canonical `_envelope` shape (kaizen meta + data.findings + verdict).

## What this skill is NOT

- **Not a replacement for hand-written axes** with non-trivial logic.
  If your axis needs custom state, multi-pass walking, or cross-file
  reasoning, write a dedicated Python axis under
  `scripts/quality/<name>.py`.
- **Not a runtime profiler.** This is structural / regex / AST scan,
  not execution-tracing.

## When to use

- Adding a new coverage axis whose check is a simple grep, a known
  AST rule, or a file-pairing assertion.
- Retrofitting existing standalone-Python axes (per blueprint
  Phase 2 — deferred arc).

## CLI

```bash
kaizen-axis-runner list                          # list axes under domain/axes/
kaizen-axis-runner run --axis reference_demo     # run one axis
kaizen-axis-runner run --axis ./path/to/my.yaml --root /some/dir
kaizen-axis-runner report --axis reference_demo  # alias for run
```

The `--axis` arg accepts a stem (resolved under `domain/axes/`,
trying `<stem>`, `<stem>.yaml`, `<stem>.yml`) OR an absolute path.

## Axis YAML shape

Source-of-truth schema:
`schemas/workflow/schemas/axis.schema.json`.

```yaml
name: trailing-ws                   # kebab-case identifier
description: scans markdown for trailing whitespace
scan_spec:
  type: grep                        # one of: grep | ast-rule | file-coverage
  pattern: " +$"
  glob: "**/*.md"
verdict_rule:
  green_max: 0                      # findings ≤ this → green
  yellow_max: 10                    # findings ≤ this → yellow; above → red
```

### `ast-rule` variant

```yaml
scan_spec:
  type: ast-rule
  rule: class-camelcase             # or: subprocess-rc-check
  glob: "**/*.py"
  params: {}                        # reserved for per-rule tuning
```

Available rules (extend in `axis_runner_rules.py::_AST_RULE_IMPLS`):
- `class-camelcase` — flags non-CamelCase class names
- `subprocess-rc-check` — flags bare-Expr `subprocess.run(...)` w/o `check=True`

### `file-coverage` variant

```yaml
scan_spec:
  type: file-coverage
  expected_glob: "scripts/quality/*.py"
  actual_glob: "tests/test_*.py"
```

Match heuristic: stem of expected file contains-or-is-contained in
stem of some actual file (covers both `name.py` ↔ `test_name.py`
and the reverse).

## MCP surface

The runner mounts under the kaizen MCP gateway as
`("axis_runner", "axis_runner_mcp")`. Tools:

- `list_axes()`          → envelope.data.axes (stems)
- `run_axis(name)`       → envelope from running one axis
- `report(name)`         → alias for run_axis

## Files

| File | Purpose |
|---|---|
| `schemas/workflow/schemas/axis.schema.json` | JSON Schema SSOT (oneOf 3 scan-spec variants) |
| `schemas/workflow/axes/*.yaml`              | Declared axes |
| `scripts/quality/axis_runner.py`                  | Loader + dispatcher + CLI |
| `scripts/quality/axis_runner_rules.py`            | Pure-fn rule library |
| `scripts/mcp/axis_runner_mcp.py`                  | FastMCP wrapper |
| `bin/kaizen-axis-runner`                          | CLI symlink |
| `bin/kaizen-axis-runner-mcp`                      | MCP-server symlink |

## Iron-law alignment

- `bin-wrapper-per-cli`: each CLI entry point has its own bin/ symlink
- `plugin-manifest-permissions`: 5 explicit permission entries
- `paired-tests`: 4 test files (test_axis_runner / _rules / _reference_demo / _mcp)
- `schema-driven-domain`: scan-spec lives in YAML + JSON Schema
- `lazy-heavy-deps`: jsonschema is graceful-fallback (try/except on import)
- `sandbox-tests`: all tests use `tempfile.TemporaryDirectory()`
- `cli-naming-consistency`: `argparse(prog="kaizen-axis-runner")` matches
  `_envelope.emitter("kaizen-axis-runner", ...)`
