---
name: schema-driven-cli
description: Reusable lens pattern for kaizen CLIs — declare subcommands + input/output JSON Schemas in a v2 manifest yaml, validate I/O via lens.py before/after each call, and emit the canonical envelope. Pairs with _envelope.py and BucketWalker for data-driven rubrics. Use when adding a new CLI feature or refactoring an existing one to make its contract discoverable + machine-checked.
metadata:
  version: "1.0"
---

# Schema-driven CLI — the kaizen lens pattern

## ⚠ Iron Law — read in full

Skip nothing. The four pieces (manifest, schemas, rule-walker,
envelope) only hang together as a whole — skim to "Quick reference"
and you'll skip the failure-mode rules that prevent silent
shape-drift in production tools.

## What this skill IS

A reusable runtime + schema set for declaring kaizen CLI subcommands
in YAML and validating their I/O against JSON Schemas at the lens
boundary. Pairs with `_envelope.py` (the canonical output envelope)
to form a single discoverable contract per feature.

The pattern proves out three classes of failure that bare-stdout CLIs
hit at scale:

1. **Silent shape drift** — a tool changes its `--json` payload; every
   downstream consumer breaks unannounced. Schema validation at lens
   boundary catches the drift the moment it ships.
2. **Hidden contract** — agents and MCP clients have to read prose to
   know what a tool accepts/returns. The v2 manifest is the
   *discoverable* contract.
3. **Prose-encoded business rules** — rubrics, classifiers, filter
   sets coded in markdown make Claude re-interpret them per session.
   The `BucketWalker` shape moves those rules into data-driven YAML
   that's deterministic across runs.

## When to use it

| Use the lens when... | Skip the lens when... |
|---|---|
| New multi-subcommand CLI feature | One-shot script with no `--json` flag |
| Refactoring an existing feature with `--json` output | The feature is a pure shell script (`.sh`) |
| Output shape is consumed by downstream tools / MCP | Output is purely human-readable text |
| The feature has a rubric, classifier, or rule set | The behavior is single-branch logic |
| You want agent + MCP to share one contract | Internal helper module (no CLI surface) |

## The four pieces

```text
skills/<feature>/
├── SKILL.md                                 — agent-facing prose
├── domain/
│   ├── <feature>.yaml                       — v2 manifest (subcommands → schemas)
│   ├── <rule-set>.yaml                      — data-driven rule yaml (rubric/checks/...)
│   └── schemas/
│       ├── <sub-1>-in.schema.json           — per-subcommand input
│       ├── <sub-1>-out.schema.json          — per-subcommand output payload
│       └── ...                              — one pair per subcommand that opts in
plugins/kaizen/skills/workflow/scripts/
└── <feature>.py                             — CLI that loads the manifest + emits via lens
```

### Piece 1 — The v2 manifest

`skills/<feature>/domain/<feature>.yaml` declares the feature's
subcommand → schema map. Validated against
`skills/schema-driven-cli/domain/schemas/feature-manifest.schema.json`.

```yaml
version: 2
feature: handoff                   # kebab-case, matches dir name

subcommands:
  verify:
    description: structural verification of a handoff YAML
    input_schema:  schemas/verify-in.schema.json     # relative to manifest
    output_schema: schemas/verify-report.schema.json
  scaffold:
    description: git-driven YAML pre-fill
    input_schema:  schemas/scaffold-in.schema.json
    output_schema: schemas/scaffold-out.schema.json
```

Subcommands may declare neither, one, or both schemas. Missing schema
→ the matching `validate_*` no-ops. Useful for subcommands whose
output isn't structured (e.g. a `print path` that just emits a string).

### Piece 2 — Per-subcommand JSON Schemas

One file per direction per subcommand. Use Draft 2020-12. Keep
`$id` pointed at the canonical URL so downstream tools can
deref. Examples:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": ".../verify-report.schema.json",
  "title": "Handoff verify report",
  "type": "object",
  "required": ["file_checks", "verdict"],
  "properties": {
    "file_checks": {"type": "array", "items": {"$ref": "#/$defs/FileCheck"}},
    "verdict":     {"enum": ["clean", "drift", "regression"]}
  },
  "$defs": {
    "FileCheck": {"required": ["path","status"], "properties": {...}}
  }
}
```

Cross-reference shared structures via `$defs` + `$ref`. Don't inline
the same object three times.

### Piece 3 — Rule yamls (data-driven classifiers)

When a subcommand's behavior is a rubric / classifier / decision
table, encode the rules in YAML. The `BucketWalker` API in `lens.py`
walks it deterministically.

```yaml
# domain/outcome-rubric.yaml — drives the handoff auto-finalize bucket pick
rules:
  - bucket: SUCCEEDED
    require_all:
      - {signal: completed_ratio, op: ">=", value: 1.0}
      - {signal: test_delta,      op: ">=", value: 0}
      - {signal: blocker_count,   op: "==", value: 0}
  - bucket: PARTIAL_PLUS
    require_all:
      - {signal: completed_ratio, op: ">=", value: 0.7}
      - {signal: blocker_count,   op: "==", value: 0}
  - bucket: FAILED
    require_any:
      - {signal: completed_ratio, op: "<",  value: 0.3}
      - {signal: test_delta,      op: "<",  value: 0}

confidence_threshold: 0.85
fallback: NEEDS_AGENT
```

Rule shape:
- `bucket` — label assigned when this rule fires.
- `require_all` — list of conditions; all must hold. Optional.
- `require_any` — list of conditions; at least one must hold. Optional.
- A rule may declare both; both must hold (ALL-then-ANY semantics).
- Condition: `{signal, op, value}` — `op` ∈ `>=, >, <=, <, ==, !=`.
  Unknown op → `RuleError` at load time.
- Missing signal in the input → that condition fails (no `KeyError`).

**First match wins.** Order rules from strictest to most permissive,
ending with the catchall(s). No rule matches → fallback bucket.

### Piece 4 — The envelope (already in place via `_envelope.py`)

Every subcommand's `--json` output flows through
`_envelope.emitter()`. The canonical envelope shape:

```json
{
  "kaizen": {
    "schema_version": 1,
    "tool": "kaizen-handoff",
    "plugin_version": "1.40.0",
    "tool_version": "1.0.0",
    "command": "handoff.py verify --file X.yaml --json"
  },
  "verdict": "clean",
  "counts": {"warnings": 0, "errors": 0},
  "data": { "...": "subcommand-specific payload, schema-validated" }
}
```

`data` carries the subcommand-specific payload — validated against
the `output_schema` declared in the manifest. Consumers downstream
(agents, MCP, pipelines) treat the envelope as the single contract:
read `verdict` for go/no-go, `counts` for severity buckets, `data`
for the rich content.

## Wiring the lens into a CLI

### Step 1 — declare the manifest

Write `skills/<feature>/domain/<feature>.yaml` (v2 shape above).
Write per-subcommand input/output schemas in `domain/schemas/`.

### Step 2 — load the manifest at CLI startup

```python
# In skills/workflow/scripts/<feature>.py
from pathlib import Path
import lens

_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "<feature>" / "domain" / "<feature>.yaml"
)
_MANIFEST = lens.Manifest.load(_MANIFEST_PATH)
```

The load itself validates the manifest against the meta-schema. A
malformed manifest fails fast at module import time, not at first
call.

### Step 3 — emit through the lens at each subcommand

Two patterns. Pick the one that fits the handler shape:

**Pattern A — minimal: lens_emit at the JSON branch**

```python
def _cmd_verify(args) -> int:
    data = run_verification(args)
    if args.json:
        lens.lens_emit(
            "kaizen-<feature>", _MANIFEST, "verify",
            data=data, verdict=data["verdict"],
            tool_version="1.0.0",
        )
    else:
        print(render_text(data))
    return 0
```

**Pattern B — full dispatch: lens_dispatch when input is structured**

```python
def _cmd_verify(args) -> int:
    return lens.lens_dispatch(
        "kaizen-<feature>", _MANIFEST, "verify",
        input_data={"file": args.file, "since": args.since},
        handler=lambda inp: run_verification(inp),
        tool_version="1.0.0",
    )
```

Pattern B validates input AND output and emits the envelope in one
call. Use it when:
- The subcommand reads structured args (file paths, JSON stdin)
- You want the input contract enforced by the lens, not by argparse
- The handler is a clean pure-ish function

### Step 4 — walk rule yamls deterministically

When a subcommand has a classifier or rubric, prefer the
`BucketWalker` over inline if/elif chains:

```python
import lens
_RUBRIC = lens.BucketWalker.from_yaml(
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "handoff" / "domain" / "outcome-rubric.yaml"
)

def assess(signals: dict) -> str:
    result = _RUBRIC.evaluate(signals)
    if result.method == "fallback":
        # Hand off to LLM / agent / user for ambiguous cases.
        return None
    return result.bucket
```

Changing a threshold is a 1-line YAML edit; the code never moves.

## Test discipline

The TDD pattern for a lens-wired subcommand:

1. **Write the output schema FIRST.** Tests assert that subcommand
   output validates against the schema — making the schema
   load-bearing from day 1.

2. **Test the manifest load + each subcommand presence** —
   guards against accidental schema-path typos:

   ```python
   def test_verify_subcommand_in_manifest(self):
       m = lens.Manifest.load(_MANIFEST_PATH)
       sub = m.get("verify")
       self.assertTrue(sub.output_schema_path.is_file())
   ```

3. **Test the rule yaml's classifications** — one per row of the
   decision table:

   ```python
   def test_succeeded_bucket(self):
       w = lens.BucketWalker.from_yaml(_RUBRIC_PATH)
       r = w.evaluate({"completed_ratio": 1.0, "test_delta": 0,
                        "blocker_count": 0})
       self.assertEqual(r.bucket, "SUCCEEDED")
   ```

4. **Subprocess-test the CLI** — invoke `python3 <feature>.py verb
   --json` in a subprocess and assert the envelope shape (use
   `jsonschema.validate` against the tool-output schema +
   subcommand's output schema).

5. **Sandbox via `KAIZEN_*_PATH` env vars** — no real `~/.claude/`
   writes during CI.

## Iron-law interaction

- **bin-wrapper-per-cli** — the lens is a library (`lens.py`), no
  bin needed.
- **plugin-manifest-permissions** — `lens.py` lands under
  `skills/workflow/scripts/` so the existing wildcard perm covers
  it. No explicit entry needed.
- **schema-driven domain yaml** (soft iron-law) — this skill MAKES
  the soft law concrete + machine-checkable.

## Migration: turning an existing CLI into a lens consumer

Order of operations (each step independently mergeable):

1. **Add the v2 manifest** declaring existing subcommands with
   `description:` only (no schemas yet). Loads as a no-op.
2. **Write the output schema for ONE subcommand** (start with the
   most-consumed one). Swap its `_emit(data)` for
   `lens.lens_emit(tool, manifest, "<sub>", data)`.
3. **Add the input schema** if the subcommand reads structured args;
   migrate to `lens_dispatch`.
4. **Migrate remaining subcommands** one at a time. Each commit
   carries: the schema(s), the wiring change, and a test.
5. **Document the manifest path in the feature's SKILL.md** so
   downstream consumers know where to find the contract.

The lens is additive — partial migration is fine; missing schemas
no-op.

## What this skill is NOT

- A replacement for `_envelope.py` — the envelope is the OUTPUT
  shape; the lens is the contract VALIDATOR around it.
- A YAML-to-Python codegen tool. The manifest is metadata, not
  generated source.
- A general workflow engine. Use `flow.py`'s `AsyncNode`/`AsyncFlow`
  for multi-step async pipelines; the lens is per-subcommand.

## Canonical exemplar

The handoff feature is the reference consumer:

- Manifest: `skills/handoff/domain/handoff.yaml` (v2)
- Schemas: `skills/handoff/domain/schemas/*.schema.json`
- Rule yaml: `skills/handoff/domain/outcome-rubric.yaml`
- CLI: `skills/workflow/scripts/handoff.py`

Read those four files end-to-end after this skill before applying the
pattern to your own feature.
