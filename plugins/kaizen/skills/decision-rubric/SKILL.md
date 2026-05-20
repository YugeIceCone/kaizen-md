---
name: decision-rubric
description: Reusable rubric / classifier pattern for kaizen features — first-match-wins YAML rules walked by schema_cli.BucketWalker. Use when a decision can be encoded as signals + thresholds + ordered buckets, with an agent fallback for ambiguous cases. Ships kaizen-rubric CLI for prototyping rubrics before wiring into a feature CLI. Triggers on "outcome bucket", "classifier rule", "severity rollup", "verdict assignment", "deterministic decision", "rubric yaml", "BucketWalker".
metadata:
  version: "1.0"
---

# Decision rubric — data-driven classifier pattern

## ⚠ Iron Law — read in full

Skip nothing. The five sections (signal computer, rule shape, ops
vocabulary, ordering discipline, NEEDS_AGENT contract) only work
together — skim to "Quick reference" and you'll wire a rubric that
silently mis-classifies because rules fired in the wrong order.

## What this skill IS

The **rubric pattern** + its runtime + a prototyping CLI:

1. A SHAPE for encoding classification rules in YAML — signals,
   thresholds, ordered buckets, fallback.
2. A WALKER (`schema_cli.BucketWalker`) that applies rules
   deterministically — first match wins.
3. A SIGNAL-COMPUTER discipline — pure-function extraction of the
   inputs the rubric reads.
4. A NEEDS_AGENT contract — when the rubric can't decide, the agent
   takes over (Haiku via SDK in scripted runs; inline Opus in
   interactive sessions).
5. A `kaizen-rubric` CLI for prototyping rules before writing the
   consumer feature.

Pairs with `schema-driven-cli` — the lens skill — which is where
`BucketWalker` lives. This skill is about HOW TO USE the walker;
the lens skill is about the broader contract surface (manifests +
schemas + envelope).

## When to use it

| Use a rubric when... | Skip a rubric when... |
|---|---|
| The decision boundary has measurable signals (counts, ratios, severities) | The decision is genuinely qualitative (style, taste, judgment) |
| Buckets are mutually exclusive + exhaustive | Output is continuous (a number, not a label) |
| You want the same decision across runs/agents | Each invocation legitimately needs human judgment |
| The rule-set will evolve and you want it editable in YAML | The logic is genuinely one-off |
| Multiple consumers will route on the bucket | The decision is internal scratch state |

## Canonical exemplar

The handoff outcome assessor is the reference consumer:

- Rule yaml: `schemas/handoff/outcome-rubric.yaml`
- Signal computer: `scripts/handoff/handoff.py::_compute_assessment_signals`
- Consumer CLI: `kaizen-handoff assess` (`_cmd_assess` in same file)
- Tests: `tests/test_handoff_assess.py`

Read those four files end-to-end after this skill before applying
the pattern to your own feature.

## The 5 pieces

### Piece 1 — The rule yaml

```yaml
# skills/<feature>/domain/<feature>-rubric.yaml
rules:
  - bucket: SUCCEEDED
    require_all:
      - {signal: completed_ratio,      op: ">=", value: 1.0}
      - {signal: test_delta,           op: ">=", value: 0}
      - {signal: blocker_count,        op: "==", value: 0}
      - {signal: next_blocking_count,  op: "==", value: 0}

  - bucket: FAILED
    require_any:
      - {signal: test_delta,      op: "<",  value: 0}
      - {signal: completed_ratio, op: "<",  value: 0.2}

  - bucket: PARTIAL_PLUS
    require_all:
      - {signal: completed_ratio,      op: ">=", value: 0.7}
      - {signal: test_delta,           op: ">=", value: 0}
      - {signal: blocker_count,        op: "==", value: 0}

  - bucket: PARTIAL_MINUS
    require_any:
      - {signal: blocker_count,        op: ">",  value: 0}
      - {signal: completed_ratio,      op: ">=", value: 0.2}

confidence_threshold: 0.85
fallback: NEEDS_AGENT
```

- Each rule declares a **bucket** label and ONE of `require_all` /
  `require_any` (a rule with both = ALL-then-ANY semantics).
- A condition is `{signal, op, value}` — a comparison between an
  input signal and a literal. Ops in §3.
- **First match wins.** Order matters — strictest at the top, most
  permissive last.
- `confidence_threshold` is the floor for the deterministic path
  (1.0 when a rule fires). When no rule matches, the result's
  `confidence` is set to this threshold + bucket becomes `fallback`.
- `fallback` is the label assigned when no rule fires. Conventionally
  `NEEDS_AGENT` so downstream consumers know to escalate.

### Piece 2 — The signal computer

```python
# In your feature's CLI script, alongside the handler.

def _compute_my_signals(parsed_input: dict) -> dict:
    """Pure function. Extract the signals the rubric walks.

    No side effects, no I/O, no model calls. Just deterministic
    reads off the parsed input + a tiny amount of arithmetic /
    regex / counting. Output keys MUST match the `signal:` names
    in the rubric yaml.
    """
    done       = parsed_input.get("done_items", [])
    blockers   = parsed_input.get("blockers", [])
    next_items = parsed_input.get("next", [])
    denom = len(done) + len(blockers) + len(next_items)
    return {
        "done_count":          len(done),
        "blocker_count":       len(blockers),
        "next_blocking_count": sum(1 for n in next_items if BLOCKING_RE.search(n)),
        "completed_ratio":     round(len(done) / denom, 4) if denom else 0.0,
        "test_delta":          int(parsed_input.get("test_delta", 0)),
    }
```

Discipline:
- **Pure.** Same input → same output. No subprocess calls, no env
  reads, no clocks.
- **Bounded.** Signals are small (int / float / short string).
- **Named once.** The signal name in the rubric IS the dict key.
  Mismatches → silent "missing signal" → rule never fires.
- **Tested.** Direct unit tests on the computer (no subprocess).
  See `tests/test_handoff_assess.py::TestSignalsComputer`.

### Piece 3 — Operator vocabulary

The walker supports these ops (defined in `schema_cli.py::_OPERATORS`):

| Op   | Meaning |
|------|---------|
| `>=` | greater-or-equal |
| `>`  | strictly greater |
| `<=` | less-or-equal |
| `<`  | strictly less |
| `==` | equal |
| `!=` | not equal |

Unknown op → `RuleError` raised at `BucketWalker.from_yaml(...)`
load time (fail fast, not at first eval).

If you need richer ops (regex match, set membership, range), extend
`schema_cli._OPERATORS` and add corresponding tests. Don't sneak
custom op handling into your feature — keep the vocabulary
discoverable in one place.

### Piece 4 — Ordering discipline

**First match wins.** Order rules in this priority:

1. **Strictest "happy path" first** (e.g. `SUCCEEDED` with all `require_all`).
2. **Strictest "sad path" second** (e.g. `FAILED` with test regression).
3. **Intermediate buckets next** (`PARTIAL_PLUS`, `PARTIAL_MINUS`).
4. **Catch-all last** — usually omitted; let the `fallback` take it.

Anti-patterns:

- ❌ `PARTIAL_MINUS` rule with `require_any: [{blocker_count >= 0}]`
  at position 1 — fires for every input, hides everything below.
- ❌ Same bucket appearing twice — first wins; the second is dead code.
- ❌ Overlapping `require_any` between buckets — earlier bucket steals
  inputs the later bucket was meant to catch.

Use `kaizen-rubric eval --rubric R.yaml --signals '{...}'` to test
boundary cases before shipping.

### Piece 5 — The NEEDS_AGENT contract

When no rule matches → `bucket=fallback`, `method=fallback`,
`confidence=confidence_threshold`. The consumer of the rubric MUST
handle this case explicitly:

```python
result = walker.evaluate(signals)
if result.method == "fallback":
    # Three options for escalation, in cost order:
    # (1) Interactive Opus session — return result; agent reads, picks
    # (2) Scripted run — dispatch to Haiku via SDK with the rubric +
    #     signals as input; force structured output (--llm-assess)
    # (3) Ask the user via AskUserQuestion when present
    return _escalate(result.bucket, signals)
return result.bucket
```

Never silently use `NEEDS_AGENT` as a real bucket — it's a sentinel,
not a classification. Downstream consumers must route on
`result.method` AND `result.bucket`.

## The `kaizen-rubric` CLI

For prototyping rubrics WITHOUT writing a consumer feature first:

```bash
# Lint structural shape — catches unknown ops, malformed conditions
kaizen-rubric lint --rubric path/to/rubric.yaml

# Evaluate against a signals dict (inline JSON)
kaizen-rubric eval --rubric path/to/rubric.yaml --signals '{"x": 7}'

# Or from a JSON file
kaizen-rubric eval --rubric path/to/rubric.yaml --signals-file sigs.json

# Or from stdin (handy for piping from other tools)
echo '{"x": 7}' | kaizen-rubric eval --rubric path/to/rubric.yaml
```

Output flows through the canonical envelope (`kaizen-rubric` tool
name + envelope.data matching the BucketWalker result shape).

**Use it during rubric design** to:
1. Sanity-check the boundary cases (just-passing / just-failing /
   ambiguous-by-design).
2. Confirm rule ordering — try a signal that should fire bucket B
   and verify A isn't stealing it.
3. Validate the fallback fires for inputs you DON'T want
   classified deterministically.

## TDD discipline

When wiring a rubric into a feature:

1. **Write the rubric yaml first.** Sketch the rules in YAML
   before any Python.
2. **Lint it.** `kaizen-rubric lint --rubric R.yaml` — confirms
   structural shape.
3. **Test boundary cases.** `kaizen-rubric eval` each
   classification you expect — one test row per bucket + one for
   the fallback.
4. **Unit-test the signal computer.** Pure-function tests with
   hand-built `parsed` dicts.
5. **End-to-end test the subcommand.** Subprocess test that
   exercises the full pipeline — input → signals → walker → envelope.
6. **Schema-validate the output.** If the rubric drives a lens
   subcommand (per `schema-driven-cli`), the consumer's output
   schema captures the result shape; round-trip-validate it.

See `tests/test_handoff_assess.py` for the canonical layout.

## Common pitfalls

- **Floating-point comparisons.** `completed_ratio == 0.5` is fragile;
  prefer `>=` / `<=` on rounded values.
- **String signals with `==`.** Case-sensitive, exact-match only.
  For substring or pattern matches, compute the membership in the
  signal computer and use a boolean signal.
- **Missing signal silently fails.** If a rule references
  `signal: foo` and `foo` isn't in the computed signals dict, the
  condition is treated as unsatisfied (no `KeyError`). Always run
  `kaizen-rubric eval` with the expected signals to catch typos.
- **Implicit catch-all.** If your last bucket is `require_any` with
  one condition that's always true, you've moved the fallback INTO
  the rule set — defeating the NEEDS_AGENT contract. Let the
  walker's `fallback` field carry that role.
- **Mixing rubric + LLM in the same rule.** Rules are deterministic
  math. If a decision needs language understanding, that's the
  NEEDS_AGENT path, not a rubric condition.

## Iron-law interaction

- **bin-wrapper-per-cli** — `rubric.py` ships with `bin/kaizen-rubric`.
  Subcommands (`eval`, `lint`) dispatch within the script.
- **plugin-manifest-permissions** — `rubric.py` has its explicit perm
  entry in `plugin.json::permissions.allow`.
- **schema-driven domain yaml** — rubric YAMLs ARE the soft iron-law
  in action; this skill formalizes the pattern.

## What this skill is NOT

- A workflow engine. For multi-step async pipelines, use
  `flow.py`'s `AsyncNode`/`AsyncFlow`.
- A general decision-tree library. The walker is intentionally
  flat — first-match-wins. Trees and DAGs are a different shape.
- A replacement for LLM judgment when the decision is qualitative.
  Use the rubric for the structured 70% and let the agent handle
  the ambiguous 30% via NEEDS_AGENT.

## Quick reference

```yaml
# Rubric shape — copy into skills/<feature>/domain/<feature>-rubric.yaml
rules:
  - bucket: STRICTEST_HAPPY
    require_all: [{signal: S1, op: ">=", value: V1}, ...]
  - bucket: STRICTEST_SAD
    require_any: [{signal: S2, op: "<",  value: V2}, ...]
  - bucket: INTERMEDIATE
    require_all: [...]
confidence_threshold: 0.85
fallback: NEEDS_AGENT
```

```python
# Wiring shape — in your feature's CLI script
import schema_cli

_RUBRIC = schema_cli.BucketWalker.from_yaml(
    Path(__file__).resolve().parent.parent.parent
    / "skills" / "<feature>" / "domain" / "<feature>-rubric.yaml"
)

def _compute_signals(parsed: dict) -> dict:
    return {"S1": ..., "S2": ...}

def _cmd_assess(args) -> int:
    signals = _compute_signals(parse_input(args.file))
    result = _RUBRIC.evaluate(signals)
    if result.method == "fallback":
        ...  # escalate to agent / Haiku / user
    return _emit_envelope(result, signals)
```
