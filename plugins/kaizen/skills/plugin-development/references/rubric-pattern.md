# Decision-rubric pattern — deep dive

**Source-of-truth pointer:** `skills/decision-rubric/SKILL.md` carries
the conceptual treatment (signals → ordered buckets → fallback). This
doc is the **kaizen-plugin-specific implementation reference** —
how to wire a new feature to BucketWalker without re-discovering the
conventions.

## When to use

Pick the rubric pattern when a decision is:
- Reducible to **N quantitative signals**
- Classifiable into **2-10 named buckets**
- **Ordered** (rule precedence matters — first-match-wins)
- **Auditable** (the user must be able to read the YAML and predict
  what will fire)

Skip it when:
- One signal → one threshold (single-comparison gate; just use an `if`)
- ≥10 buckets needed (over-modelling; refactor your input space)
- Buckets need to compose (rubrics don't combine — they pick ONE)
- Decisions need to call back into LLM-judgment (use the
  decision-rubric skill's NEEDS_AGENT fallback)

## Anatomy

### Signal computer

A **pure function** in the calling module — `_compute_signals(**kwargs) → dict[str, Any]`.
NO side effects, NO I/O, NO random. Same inputs → same outputs.

```python
# scripts/<feature>.py
def _compute_signals(*, pct: int, threshold: int,
                       compact_count: int = 0,
                       peak_pct: int | None = None) -> dict:
    return {
        "pct":             int(pct),
        "threshold":       int(threshold),
        "above_threshold": 1 if pct >= threshold else 0,  # boolean → int
        "compact_count":   int(compact_count),
        "peak_pct":        int(peak_pct if peak_pct is not None else pct),
        "threshold_delta": int(pct) - int(threshold),
    }
```

**Why ints over bools:** BucketWalker compares with `>= == !=` etc.
Bools work but ints are unambiguous in YAML (no `True` vs `true`).

### Rubric YAML

Lives at `skills/<feature>/domain/rubric.yaml`:

```yaml
version: 1

rules:
  # ─── First match wins — order rules by SPECIFICITY descending ──
  - bucket: critical-block          # most specific FIRST
    require_all:
      - {signal: pct, op: ">=", value: 90}

  - bucket: threshold-block         # less specific
    require_all:
      - {signal: above_threshold, op: "==", value: 1}

  - bucket: post-compact-warn       # multi-signal rule
    require_all:
      - {signal: compact_count, op: ">=", value: 1}
      - {signal: pct, op: ">=", value: 50}

# fallback when no rule fires — bucket name only
fallback: noop

# confidence reported when fallback fires; deterministic matches always 1.0
confidence_threshold: 0.85
```

### Operators

BucketWalker supports six numeric comparators:

| op | semantics |
|---|---|
| `>=` | signal value is at least value |
| `>`  | strictly greater |
| `<=` | at most |
| `<`  | strictly less |
| `==` | equal |
| `!=` | not equal |

**No string ops** — if you need pattern matching, precompute a flag
in the signal computer (`{signal: matches_foo, op: ==, value: 1}`).

### `require_all` vs `require_any`

```yaml
rules:
  - bucket: A
    require_all: [...]    # ALL conditions must hold
  - bucket: B
    require_any: [...]    # AT LEAST ONE condition must hold
  - bucket: C
    require_all: [...]    # both keys legal but unusual
    require_any: [...]    # ALL of require_all AND ANY of require_any
```

Missing signal in input = unsatisfied condition (NOT KeyError —
BucketWalker is graceful).

### Action-mapping convention

The rubric YAML is **pure classification** — it names the bucket but
doesn't say what to do with it. Action mapping lives in **a separate
`config.yaml::on_bucket`** so policy is editable independently:

```yaml
# config.yaml
on_bucket:
  critical-block:
    decision: block
    reason_template: "🔥 CRITICAL — context at {pct}%."

  threshold-block:
    decision: block
    reason_template: "MANDATORY pre-compact handoff..."

  post-compact-warn:
    decision: systemMessage
    reason_template: "Post-compact climbing..."

  noop: null    # bucket → no action
```

This separation lets users tune behavior (template text, decision
type) without touching the rubric's classification logic.

## Runtime usage

```python
import schema_cli

walker = schema_cli.BucketWalker.from_yaml(Path("...rubric.yaml"))
signals = _compute_signals(pct=80, threshold=75, ...)
result = walker.evaluate(signals)

# result.bucket            — picked bucket name
# result.method            — "deterministic" | "fallback"
# result.confidence        — 1.0 deterministic, threshold value fallback
# result.matched_conditions / total_conditions
# result.rationale         — human-readable explanation
```

Then look up `on_bucket[result.bucket]` in your config to get the
action shape.

## Conventions to follow

1. **One rubric per feature.** Don't share a rubric YAML across
   features — the signals are feature-specific.
2. **Signal computer is pure.** Tests can call it directly with
   synthetic inputs and assert the rubric routes correctly.
3. **Schema-validate the rubric.** Ship a `rubric.schema.json`
   alongside (see `schemas/handoff/schemas/auto-rubric.schema.json`)
   so misconfigurations surface at install/test, not at runtime.
4. **Order rules SPECIFIC → GENERAL.** First-match-wins means a
   `pct >= 50` rule placed before `pct >= 90` would prevent the
   critical-block rule from ever firing.
5. **`noop` as fallback** if no-action is sensible. Otherwise pick
   a sentinel bucket that downstream code recognizes.

## Reference examples in the plugin

| Skill | Rubric file | What it classifies |
|---|---|---|
| `skills/auto-handoff/` | `domain/rubric.yaml` | Context-pressure buckets (critical-block / threshold-block / post-compact-warn / high-peak-soft-warn / noop) |
| `skills/handoff/` | `domain/outcome-rubric.yaml` | Outcome buckets (SUCCEEDED / PARTIAL_PLUS / PARTIAL_MINUS / FAILED / NEEDS_AGENT) |

Read those YAMLs as concrete templates before authoring your own.

## Testing

```python
class TestRubric(unittest.TestCase):
    def test_signal_computer_pure(self):
        from <feature> import _compute_signals
        s1 = _compute_signals(pct=80, threshold=75)
        s2 = _compute_signals(pct=80, threshold=75)
        self.assertEqual(s1, s2)  # determinism

    def test_critical_bucket_routes(self):
        import schema_cli
        walker = schema_cli.BucketWalker.from_yaml(RUBRIC_PATH)
        result = walker.evaluate({"pct": 95, "above_threshold": 1, ...})
        self.assertEqual(result.bucket, "critical-block")

    def test_rubric_validates_against_schema(self):
        import jsonschema, yaml
        rubric = yaml.safe_load(RUBRIC_PATH.read_text())
        schema = json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(rubric, schema)  # no raise
```
