# Brainstorming skill — confidence-score + deferral-bucket design

- **Date:** 2026-05-18
- **Backlog ref:** BK-012 (`.kaizen/workflow/backlog.json`)
- **Skill being modified:** `plugins/kaizen/skills/brainstorming/`
- **Related skills loaded:** `brainstorming`, `decision-rubric`, `plugin-development`
- **Status:** spec drafted, awaiting user review → writing-plans

## Motivation

The `/kaizen:brainstorming` skill today is **process-only** — it
describes how to explore an idea (explore → ask → propose → present
→ write spec) but has no formal output contract. Real-world large
brainstorms have already converged on a de-facto JSONL schema (see
`semantic-search/docs/2026-05-17-coverage-ideas.jsonl`, 300 ideas)
using `{id, round, bucket, theme, idea, tier, status, prose, tools?}`,
but the schema lives only in the producer's head — different sessions
emit subtly different field sets, and there's no deterministic
classification of which idea ships next vs gets parked.

BK-012 asks for three concrete additions:

1. Per-idea confidence (0.0–1.0)
2. Deferral threshold (configurable cutoff)
3. Auto-suggested + user-confirmable bucket

This spec lifts the de-facto schema into a typed contract, threshold-
gates it for large brainstorms only (>10 ideas), runs deterministic
classification via the existing `decision-rubric` pattern, and adds
a single batch user-confirmation step for the LLM-flagged edge cases.

## Non-goals

- Rewriting existing brainstorm JSONLs (back-compat: old files keep
  working, new contract applies forward; `kaizen-brainstorm score`
  migrates on-demand when re-scored).
- Replacing the brainstorming SKILL's process narrative — the skill
  body's question-loop discipline is untouched; only the output
  contract section is added.
- Per-idea inline user confirmation (the LLM-emit loop is fast; one
  batch-confirm at the end is the affordance).
- Cross-brainstorm analytics (filed as PHASE_2 in §Deferrals).

## Architecture

```
Brainstorming session (≥10 ideas — threshold gate)
    │
    │  LLM emits per-idea draft
    ▼
┌─────────────────────────────────┐
│ idea draft                      │
│  {theme, idea, tools?,          │
│   effort_estimate?, yagni?,     │
│   radical?, ...}                │
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐  pure fn — no I/O, no LLM
│ _compute_idea_signals(draft)    │  • length_words, has_tool_dep,
│   → signals dict                │    trigger_present, effort_bucket,
└────────────┬────────────────────┘    yagni_flag, radical_flag, novelty_score
             ▼
┌─────────────────────────────────┐  first-match-wins
│ BucketWalker(brainstorm-rubric  │  KEEP / YAGNI / RADICAL / PHASE_2 /
│   .yaml).evaluate(signals)      │  RESEARCH / NEEDS_AGENT fallback
│   → bucket + method + confidence│
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│ enriched idea row               │
│  {..draft, auto_bucket,         │
│   confidence, rationale,        │
│   rubric_version}               │
└────────────┬────────────────────┘
             │
             │  loop until all ideas scored, then ONCE
             ▼
┌─────────────────────────────────┐  presents NEEDS_AGENT items
│ AskUserQuestion (batch confirm) │  + top-3 KEEP for sanity-check;
│   → manual_bucket overrides     │  override sets manual_bucket
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐  validated by idea.schema.json
│ JSONL emit (atomic write)       │  at write boundary
│   plans/<date>-<topic>.jsonl    │
└─────────────────────────────────┘
```

## Components

### Signal computer

Pure function. Input: one idea draft dict. Output: signals dict
matching the rubric's `signal:` keys.

```python
# plugins/kaizen/skills/workflow/scripts/brainstorm.py

_TRIGGER_RE = re.compile(r"\bwhen\b|\btrigger\b|→|\bif\b.*\bthen\b", re.I)

def _compute_idea_signals(draft: dict) -> dict:
    """Pure fn — no I/O, no LLM. Mirrors handoff exemplar contract."""
    text = draft.get("idea", "")
    return {
        "length_words":     len(text.split()),
        "has_tool_dep":     bool(draft.get("tools")),
        "trigger_present":  bool(_TRIGGER_RE.search(text)),
        "effort_bucket":    draft.get("effort_estimate", "M"),
        "yagni_flag":       bool(draft.get("yagni", False)),
        "radical_flag":     bool(draft.get("radical", False)),
        "llm_confidence":   float(draft.get("confidence", 0.5)),    # LLM self-rated 0.0-1.0
        "novelty_score":    float(draft.get("novelty_score", 0.5)), # Phase 2 default
    }
```

**`llm_confidence` is the primary confidence signal** — the LLM
emits a self-rated 0.0–1.0 score per idea expressing how strongly
it believes the idea is worth pursuing. The signal computer passes
it through; the rubric reads it as input. Default 0.5 (neutral)
when missing — neutral confidence routes through structural signals
only.

This is distinct from the rubric's `confidence_threshold` (0.85) —
the latter is the rubric's confidence in its OWN classification when
a rule fires. Both end up in the output JSONL: `confidence` is
LLM-self-rated; `classification_confidence` is rubric-emitted.

Discipline (from decision-rubric Iron Laws):

- **Pure** — same input → same output. No subprocess, no env, no clock.
- **Bounded** — every signal is int / float / bool / short string.
- **Named once** — signal name in rubric IS the dict key. Mismatch → silent.
- **Tested** — pure-fn unit tests (T3).

### Rubric

`plugins/kaizen/skills/brainstorming/domain/brainstorm-rubric.yaml`:

```yaml
# 7 explicit rules + NEEDS_AGENT fallback.
# Order: strictest happy → low-confidence sad → flag-driven edge → effort/topic intermediates → length explicit → fallback.

version: 1                              # bump on any rule change; rows
                                        # carry this in `rubric_version`
rules:
  # 1. KEEP — high-confidence, tight, signal-rich, normal effort
  - bucket: KEEP
    require_all:
      - {signal: llm_confidence,  op: ">=", value: 0.85}
      - {signal: length_words,    op: ">=", value: 8}
      - {signal: length_words,    op: "<=", value: 80}
      - {signal: trigger_present, op: "==", value: true}
      - {signal: effort_bucket,   op: "!=", value: "XL"}
      - {signal: yagni_flag,      op: "==", value: false}
      - {signal: radical_flag,    op: "==", value: false}

  # 2. YAGNI — LLM-flagged anti-pattern OR very low LLM confidence
  - bucket: YAGNI
    require_any:
      - {signal: yagni_flag,     op: "==", value: true}
      - {signal: llm_confidence, op: "<",  value: 0.4}
      # ^ regardless of structural signals — LLM said "weak idea";
      #   manual_bucket via override can rescue it.

  # 3. RADICAL — LLM-flagged moonshot
  - bucket: RADICAL
    require_all:
      - {signal: radical_flag, op: "==", value: true}
      - {signal: length_words, op: ">=", value: 8}

  # 4. PHASE_2 — well-formed but XL effort (defer execution, keep design)
  - bucket: PHASE_2
    require_all:
      - {signal: llm_confidence, op: ">=", value: 0.5}
      - {signal: length_words,   op: ">=", value: 8}
      - {signal: effort_bucket,  op: "==", value: "XL"}
      - {signal: yagni_flag,     op: "==", value: false}
      - {signal: radical_flag,   op: "==", value: false}

  # 5. RESEARCH — no concrete trigger, needs validation
  - bucket: RESEARCH
    require_all:
      - {signal: llm_confidence,  op: ">=", value: 0.5}
      - {signal: length_words,    op: ">=", value: 8}
      - {signal: trigger_present, op: "==", value: false}
      - {signal: yagni_flag,      op: "==", value: false}
      - {signal: radical_flag,    op: "==", value: false}

  # 6. NEEDS_AGENT — explicit length boundary trips (not fallback)
  - bucket: NEEDS_AGENT
    require_any:
      - {signal: length_words, op: "<", value: 8}
      - {signal: length_words, op: ">", value: 120}

confidence_threshold: 0.85
fallback: NEEDS_AGENT
```

Ordering rationale (per decision-rubric skill):

- KEEP first — strictest happy path; requires high LLM confidence
  AND tight structural signals.
- YAGNI second — fires on either LLM yagni-flag OR very low confidence
  (`<0.4`). Catches "LLM was unsure but emitted anyway" cases that
  would otherwise route through PHASE_2 / RESEARCH and clutter
  next-up.
- RADICAL — flag-driven moonshot.
- PHASE_2 / RESEARCH — intermediate; both require `llm_confidence
  >= 0.5`. PHASE_2 = XL effort, RESEARCH = no concrete trigger.
- NEEDS_AGENT explicit rule — catches length boundary cases
  (`<8` or `>120` words) so the consumer sees `method=deterministic`
  rather than `method=fallback`.
- `fallback: NEEDS_AGENT` — catches the quiet zones (e.g. an idea
  with 81–120 words that doesn't match any other rule). The override
  loop surfaces these for user bucketing — intentional, not a bug.

### Override loop

After ALL ideas scored, ONE `AskUserQuestion` call (not per-idea):

- Collect every `NEEDS_AGENT` idea + the top-3 `KEEP` by confidence.
- One multiSelect-per-NEEDS_AGENT lets the user pick the final bucket.
- KEEP top-3 shown for sanity-check; override only if needed.
- Each override sets `manual_bucket`; `auto_bucket` preserved.
- **User cancels / no override** → `manual_bucket = null`, `auto_bucket`
  used as final. Best-effort; never blocking.
- **Scripted runs** (env `KAIZEN_BRAINSTORM_BATCH=1`) skip the
  AskUserQuestion entirely; NEEDS_AGENT ideas emit with
  `manual_bucket = null` + STDERR warning naming the count.

### `kaizen-brainstorm score` CLI

```
kaizen-brainstorm score \
    --input plans/<date>-<topic>.jsonl \
    --rubric plugins/kaizen/skills/brainstorming/domain/brainstorm-rubric.yaml \
    [--rewrite]        # in-place atomic; default emits to stdout
    [--force]          # required when --rewrite + rubric_version drift
    [--max-ideas N]    # default 250; env KAIZEN_BRAINSTORM_MAX_IDEAS
```

Re-scores existing JSONL through the (potentially new) rubric.
Emits `{auto_bucket, confidence, rationale, rubric_version}` per row;
never touches `manual_bucket` if already present. Output flows
through the canonical envelope (per `schema-driven-cli`).

### JSON Schema

`plugins/kaizen/skills/brainstorming/domain/schemas/idea.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "kaizen brainstorm idea row",
  "type": "object",
  "required": ["id", "theme", "idea", "confidence", "auto_bucket", "classification_confidence", "rationale", "rubric_version"],
  "properties": {
    "id":              {"type": "integer", "minimum": 1},
    "theme":           {"type": "string"},
    "idea":            {"type": "string", "minLength": 1},
    "confidence":      {"type": "number", "minimum": 0.0, "maximum": 1.0,
                        "description": "LLM self-rated 0.0-1.0; the primary signal driving bucket choice."},
    "auto_bucket":     {"enum": ["KEEP", "YAGNI", "RADICAL", "PHASE_2", "RESEARCH", "NEEDS_AGENT"]},
    "classification_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0,
                        "description": "Rubric's confidence in its own bucket assignment. Equals confidence_threshold (0.85) when a rule fires deterministically; equals fallback floor when no rule matched."},
    "rationale":       {"type": "string"},
    "rubric_version":  {"type": "string", "description": "e.g. '1' — matches version: in rubric YAML."},
    "manual_bucket":   {"oneOf": [{"enum": ["KEEP", "YAGNI", "RADICAL", "PHASE_2", "RESEARCH"]}, {"type": "null"}]},
    "tools":           {"type": "array", "items": {"type": "string"}},
    "effort_estimate": {"enum": ["XS", "S", "M", "L", "XL"]},
    "yagni":           {"type": "boolean"},
    "radical":         {"type": "boolean"},
    "novelty_score":   {"type": "number", "minimum": 0.0, "maximum": 1.0},
    "trigger_present": {"type": "boolean"},
    "prose":           {"type": "string"},
    "round":           {"type": "integer", "minimum": 1}
  },
  "additionalProperties": false
}
```

Validated at `kaizen-brainstorm score` write boundary + during the
SKILL flow when the threshold gate fires.

### SKILL.md update

`plugins/kaizen/skills/brainstorming/SKILL.md` gets one new section:

```markdown
## Threshold-gated output contract

For brainstorms with >10 ideas (configurable: `--threshold N`), the
skill emits a typed JSONL alongside the prose spec:

  plans/<date>-<topic>.jsonl    structured per-idea records
  plans/<date>-<topic>.md       narrative spec (existing)

Each idea row validates against `idea.schema.json` and carries:
  - `auto_bucket` — assigned by `brainstorm-rubric.yaml`
  - `confidence` — 0.0–1.0 from the rubric's `confidence_threshold`
  - `rationale` — one-line justification
  - `manual_bucket` — user override after the batch-confirm step

Brainstorms ≤10 ideas → prose-narration only (no JSONL).
Empty brainstorms (0 ideas) → no-op; stderr "no ideas to score".
```

## Error handling

| Failure | Response |
|---|---|
| Idea draft missing required field | `score` exits 1 with envelope.errors[] naming row id + field. SKILL flow prompts LLM to repair inline. |
| Rubric YAML malformed / unknown op | `BucketWalker.from_yaml()` raises `RuleError` at load time. `score` catches → envelope error. Pre-commit `iron-laws` catches at staging. |
| Signal computer raises (defensive — shouldn't happen) | Wrapped in try/except → bucket = `NEEDS_AGENT`, rationale = `"signal computer failed: <err>"`. Doesn't abort batch. |
| Override loop user cancels | Non-overridden ideas emit with `manual_bucket = null`. JSONL writes anyway. Best-effort. |
| JSONL write failure (disk / perms) | Atomic-write (tempfile-then-rename per `_atomic.py`). Failed write → tempfile cleaned, original untouched. |
| Rubric-version drift on `--rewrite` | Each row carries `rubric_version`. Mismatch with current rubric → stderr warn + require `--force`. |
| Under-threshold brainstorm (≤10) | No-op for the structured path. Prose-narration only. No error code. |
| Empty brainstorm (0 ideas) | Skip rubric + JSONL entirely. Log "no ideas surfaced — nothing to score." Exit 0. |
| `--max-ideas N` exceeded (default 250) | Hard-stop with envelope error naming count. Override: `KAIZEN_BRAINSTORM_MAX_IDEAS=N` env. |
| `NEEDS_AGENT` final bucket | Always escalated via override loop. Suppressed only by `KAIZEN_BRAINSTORM_BATCH=1` (scripted) with STDERR warn. |

## Testing — 8 test layers

| File | What it tests |
|---|---|
| `tests/test_brainstorm_rubric_lint.py` | `kaizen-rubric lint --rubric brainstorm-rubric.yaml` exits 0. Catches unknown ops, malformed conditions, signal-name typos. |
| `tests/test_brainstorm_rubric_cases.py` | One test per bucket — signals dict → expected bucket. Plus ordering traps (a signal set that should fire B and proves A doesn't steal it). |
| `tests/test_brainstorm_signals.py` | `_compute_idea_signals({...})` round-trip per signal. Edge: empty idea → length_words=0. Missing tools → has_tool_dep=False. Missing effort_estimate → "M". |
| `tests/test_brainstorm_score_cli.py` | Subprocess: 5-row JSONL in → all 5 rows get auto_bucket+confidence+rationale. `--rewrite` atomic. `--max-ideas 3` against 5-row → exit 1. rubric_version drift → stderr + needs `--force`. |
| `tests/test_brainstorm_schema.py` | Every row emitted by score validates against idea.schema.json. Required-field-missing draft → validator rejects. |
| `tests/test_brainstorm_override.py` | T6: manual_bucket set → auto_bucket preserved. `--rewrite` never touches existing manual_bucket. Empty brainstorm → no JSONL. T6b: mocked AskUserQuestion stub returning fixed manual_bucket → override propagates correctly. |
| `tests/test_brainstorm_skill_flow.py` | Under-threshold (5 ideas, default 10) → prose-narration; no JSONL. Over-threshold (15 ideas) → JSONL emitted with all 15 rows. |
| `tests/test_brainstorm_ollama_live.py` | Real local LLM (Ollama) generates synthetic ideas with yagni/radical-flavored prompts; assert flag signals propagate to correct buckets. Graceful-skip when Ollama at :11434 unreachable (per `pref-optional-feature-graceful-fallback`, matching `test_gold_mine_ollama_live.py`). |

The gate's `affected-tests` will auto-pull the full T1-T8 suite when
`_compute_idea_signals` or `brainstorm-rubric.yaml` change.

## File layout

```
plugins/kaizen/
├── bin/
│   └── kaizen-brainstorm                                    NEW (symlink)
├── skills/
│   ├── brainstorming/
│   │   ├── SKILL.md                                         MODIFY (+§Threshold-gated)
│   │   └── domain/
│   │       ├── brainstorm-rubric.yaml                       NEW
│   │       └── schemas/idea.schema.json                     NEW
│   └── workflow/scripts/
│       └── brainstorm.py                                    NEW
├── tests/
│   ├── test_brainstorm_rubric_lint.py                       NEW
│   ├── test_brainstorm_rubric_cases.py                      NEW
│   ├── test_brainstorm_signals.py                           NEW
│   ├── test_brainstorm_score_cli.py                         NEW
│   ├── test_brainstorm_schema.py                            NEW
│   ├── test_brainstorm_override.py                          NEW (T6 + T6b)
│   ├── test_brainstorm_skill_flow.py                        NEW
│   └── test_brainstorm_ollama_live.py                       NEW (graceful-skip)
└── .claude-plugin/plugin.json                               MODIFY (perms += kaizen-brainstorm)
```

Iron-laws alignment:

- `bin-wrapper-per-cli` — `bin/kaizen-brainstorm` → `brainstorm.py`
- `plugin-manifest-permissions` — explicit perm entry in `plugin.json`
- `schema-driven domain yaml` — `brainstorm-rubric.yaml` + `idea.schema.json`
- `paired-tests` — every new script + skill change has a sibling test file

## Phase 2 deferrals (file at spec-commit time)

| Idea # | Item | Trigger |
|---|---|---|
| 3 | `signal:novelty_score` (Jaccard idea-overlap) | First duplicate-idea complaint or rubric-tuning evidence |
| 16 | `kaizen-brainstorm stats` subcommand | Rubric drift evidence (bucket distribution shifts ≥20% across 3 brainstorms) |
| 18 | Pre-commit gate nudge (`*-brainstorm.md` w/o sibling `.jsonl`) | First real "I forgot to score it" incident |

Filed as `kaizen backlog add --section parked` after spec commits.

## Back-compat / migration

- Existing `plans/2026-05-17-coverage-ideas.jsonl` and similar pre-existing
  JSONLs are left as-is. `kaizen-brainstorm score --input <old>.jsonl`
  migrates them on-demand; no batch migration.
- `visual-companion.md` + `spec-document-reviewer-prompt.md` untouched.
- Brainstorming SKILL.md additions are append-only; the existing
  question-loop / 2-3-approaches / per-section-approval flow is unchanged.

## Open questions for implementation plan

These need decisions at writing-plans time but aren't blockers for the spec:

1. **CLI entry point shape** — argparse subcommands (`score` only for
   now) or single-purpose (`kaizen-brainstorm-score`)? Recommendation:
   subcommand shape, ready for `stats` in Phase 2.
2. **Ollama model choice for T8** — already pinned via
   `KAIZEN_OLLAMA_CHAT_MODEL`? Match `test_gold_mine_ollama_live.py`.
3. **`confidence` vs `classification_confidence` naming** — the schema
   intentionally exposes both. If the writing-plans pass discovers
   downstream consumers can only carry one, recommend keeping the
   LLM-rated `confidence` and dropping `classification_confidence`
   (the latter can always be derived from `auto_bucket != NEEDS_AGENT`
   = "rule fired deterministically").

Resolved during spec self-review:

- ~~`rubric_version` derivation~~ — explicit `version:` key in
  the rubric YAML; bumped manually on any rule change; rows carry the
  string in their `rubric_version` field.

## References

- Backlog item: `.kaizen/workflow/backlog.json` BK-012
- Decision-rubric exemplar: `plugins/kaizen/skills/handoff/domain/outcome-rubric.yaml`
- Signal-computer exemplar: `plugins/kaizen/skills/workflow/scripts/handoff.py::_compute_assessment_signals`
- Existing brainstorm JSONL (de-facto schema source): `~/workspace/semantic-search/docs/2026-05-17-coverage-ideas.jsonl`
- 20-idea brainstorm session (this spec): `/tmp/bk012-brainstorm-20.jsonl`
- arXiv research: rate-limited at spec time; gap noted, not skipped silently. Re-check before writing-plans for any recent LLM-confidence-calibration work that would change `confidence_threshold` choice.
