# Brainstorming confidence-score + deferral-bucket — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the de-facto JSONL brainstorm schema into a typed contract with per-idea LLM confidence + deterministic rubric classification + threshold-gated emission + batch-confirm override loop.

**Architecture:** Pure-fn signal computer → `schema_cli.BucketWalker` rubric → JSON-schema-validated row emit → single batch `AskUserQuestion` for NEEDS_AGENT overrides. Reuses the handoff-assess exemplar end-to-end. No new abstractions; same lens contract.

**Tech Stack:** Python 3 stdlib + PyYAML + jsonschema (optional, soft-fails), `schema_cli.BucketWalker`, `_atomic.atomic_write`, `_envelope.emitter`, argparse subcommands. Tests via stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-05-18-brainstorming-confidence-score-design.md`

**Resolved open questions** (from spec §Open questions for implementation plan):

1. **CLI shape** — argparse subcommands. `kaizen-brainstorm score` for v1; surface ready for `stats` in Phase 2.
2. **Ollama model for T8** — `granite4.1:8b`, matching `test_gold_mine_ollama_live.py:46`. Opt-in via `KAIZEN_BRAINSTORM_TEST_LIVE=1`.
3. **`confidence` vs `classification_confidence`** — keep BOTH in `idea.schema.json`. `confidence` is LLM-self-rated input; `classification_confidence` is rubric-emitted output (= 1.0 deterministic / 0.85 fallback per `BucketWalker.evaluate()` contract).

**Phase-2 deferrals** (parked in P9 as backlog items, NOT implemented):
- `signal: novelty_score` Jaccard-overlap signal — trigger: first dup-idea complaint
- `kaizen-brainstorm stats` subcommand — trigger: ≥20% distribution drift across 3 brainstorms
- Pre-commit gate nudge (sibling-`.jsonl`-missing) — trigger: first "forgot to score" incident

---

## File Structure

```
plugins/kaizen/
├── bin/
│   └── kaizen-brainstorm                                    NEW (symlink to brainstorm.py)
├── skills/
│   ├── brainstorming/
│   │   ├── SKILL.md                                         MODIFY (+§Threshold-gated)
│   │   └── domain/                                          NEW dir
│   │       ├── brainstorm-rubric.yaml                       NEW (7 rules, fallback NEEDS_AGENT)
│   │       └── schemas/
│   │           └── idea.schema.json                         NEW (15 props, 8 required)
│   └── workflow/scripts/
│       └── brainstorm.py                                    NEW (signal computer + CLI + override)
├── tests/
│   ├── test_brainstorm_rubric_lint.py                       NEW (T1)
│   ├── test_brainstorm_rubric_cases.py                      NEW (T2)
│   ├── test_brainstorm_signals.py                           NEW (T3)
│   ├── test_brainstorm_score_cli.py                         NEW (T4)
│   ├── test_brainstorm_schema.py                            NEW (T5)
│   ├── test_brainstorm_override.py                          NEW (T6 + T6b)
│   ├── test_brainstorm_skill_flow.py                        NEW (T7)
│   └── test_brainstorm_ollama_live.py                       NEW (T8, graceful-skip)
└── .claude-plugin/plugin.json                               MODIFY (perms += kaizen-brainstorm)
```

Each file has one clear responsibility:
- `brainstorm.py` — module with `_compute_idea_signals`, `score_jsonl`, `run_override_loop`, `main()` argparse.
- `brainstorm-rubric.yaml` — data only, walked by `BucketWalker`.
- `idea.schema.json` — output contract, validated at write boundary.
- Each test file — one test layer, independent.

---

## Task 1: P1 — Rubric YAML + lint test (T1)

**Files:**
- Create: `plugins/kaizen/skills/brainstorming/domain/brainstorm-rubric.yaml`
- Create: `plugins/kaizen/tests/test_brainstorm_rubric_lint.py`

- [ ] **Step 1.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_rubric_lint.py`:

```python
"""T1: brainstorm-rubric.yaml passes `kaizen-rubric lint`.

Catches unknown ops, malformed conditions, signal-name typos at
test-time so the rubric ships green.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"
_RUBRIC_CLI = _KZ / "skills/workflow/scripts/rubric.py"


class TestBrainstormRubricLint(unittest.TestCase):
    def test_rubric_file_exists(self):
        self.assertTrue(_RUBRIC.is_file(), f"missing rubric: {_RUBRIC}")

    def test_kaizen_rubric_lint_passes(self):
        r = subprocess.run(
            [sys.executable, str(_RUBRIC_CLI), "lint",
             "--rubric", str(_RUBRIC)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0,
            f"lint failed:\nstdout: {r.stdout}\nstderr: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 1.2: Run test, watch it fail**

```bash
cd /home/cherry86/workspace/kaizen-md/plugins/kaizen
python3 -m unittest tests.test_brainstorm_rubric_lint -v
```

Expected: FAIL — `missing rubric: .../brainstorm-rubric.yaml` (assertion error in test_rubric_file_exists).

- [ ] **Step 1.3: Create the rubric YAML (GREEN)**

Create `plugins/kaizen/skills/brainstorming/domain/brainstorm-rubric.yaml` per spec §Rubric (lines 137–197). Use this exact content:

```yaml
# Brainstorming idea-classification rubric — data-driven, walked by
# schema_cli.BucketWalker. The `kaizen-brainstorm score` CLI reads this
# to assign auto_bucket per idea from mechanical signals computed by
# brainstorm._compute_idea_signals.
#
# Signals computed:
#   - length_words       int    — len(idea.split())
#   - has_tool_dep       bool   — tools[] non-empty
#   - trigger_present    bool   — text matches \bwhen|trigger|→|\bif\b.*\bthen\b
#   - effort_bucket      str    — draft.effort_estimate or "M"
#   - yagni_flag         bool   — draft.yagni
#   - radical_flag       bool   — draft.radical
#   - llm_confidence     float  — draft.confidence (0.0-1.0), default 0.5
#   - novelty_score      float  — draft.novelty_score, default 0.5 (Phase 2 default)
#
# First-match wins. Order: strictest happy → low-confidence sad →
# flag-driven edge → effort/topic intermediates → length explicit → fallback.

version: 1

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

- [ ] **Step 1.4: Re-run test, watch it pass**

```bash
python3 -m unittest tests.test_brainstorm_rubric_lint -v
```

Expected: 2 tests passed.

- [ ] **Step 1.5: Commit**

```bash
git add plugins/kaizen/skills/brainstorming/domain/brainstorm-rubric.yaml \
        plugins/kaizen/tests/test_brainstorm_rubric_lint.py
git commit -m "feat(brainstorm): rubric YAML + T1 lint test (BK-012 P1)"
```

---

## Task 2: P2 — Rubric cases test (T2)

**Files:**
- Create: `plugins/kaizen/tests/test_brainstorm_rubric_cases.py`

The rubric YAML already exists from P1. P2 proves each rule fires correctly and tests ordering traps.

- [ ] **Step 2.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_rubric_cases.py`:

```python
"""T2: brainstorm-rubric — bucket-per-signals + ordering traps.

One test per bucket: build a signals dict, assert BucketWalker
returns the expected bucket. Plus ordering traps: a signal-set that
should fire B and proves A doesn't steal it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import schema_cli  # noqa: E402

_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"


def _walker():
    return schema_cli.BucketWalker.from_yaml(_RUBRIC)


def _signals(**over):
    """Neutral baseline; override keys."""
    base = {
        "length_words":     20,
        "has_tool_dep":     False,
        "trigger_present":  True,
        "effort_bucket":    "M",
        "yagni_flag":       False,
        "radical_flag":     False,
        "llm_confidence":   0.9,
        "novelty_score":    0.5,
    }
    base.update(over)
    return base


class TestBrainstormRubricCases(unittest.TestCase):
    def setUp(self):
        self.w = _walker()

    # --- per-bucket happy paths ----------------------------------

    def test_keep_high_confidence_normal_effort(self):
        r = self.w.evaluate(_signals(llm_confidence=0.9, effort_bucket="M"))
        self.assertEqual(r.bucket, "KEEP")
        self.assertEqual(r.method, "deterministic")

    def test_yagni_flag_overrides(self):
        r = self.w.evaluate(_signals(yagni_flag=True))
        self.assertEqual(r.bucket, "YAGNI")

    def test_yagni_low_confidence_cascade(self):
        r = self.w.evaluate(_signals(llm_confidence=0.3))
        self.assertEqual(r.bucket, "YAGNI")

    def test_radical_flag(self):
        r = self.w.evaluate(_signals(radical_flag=True, llm_confidence=0.7))
        self.assertEqual(r.bucket, "RADICAL")

    def test_phase_2_xl_effort(self):
        r = self.w.evaluate(_signals(effort_bucket="XL", llm_confidence=0.7))
        self.assertEqual(r.bucket, "PHASE_2")

    def test_research_no_trigger(self):
        r = self.w.evaluate(_signals(trigger_present=False, llm_confidence=0.7))
        self.assertEqual(r.bucket, "RESEARCH")

    def test_needs_agent_short_idea(self):
        r = self.w.evaluate(_signals(length_words=5))
        self.assertEqual(r.bucket, "NEEDS_AGENT")
        self.assertEqual(r.method, "deterministic")

    def test_needs_agent_long_idea(self):
        r = self.w.evaluate(_signals(length_words=200))
        self.assertEqual(r.bucket, "NEEDS_AGENT")

    # --- ordering traps ------------------------------------------

    def test_yagni_beats_keep_when_flag_set(self):
        """yagni_flag=true MUST fire YAGNI even with KEEP-shape signals."""
        r = self.w.evaluate(_signals(yagni_flag=True, llm_confidence=0.95))
        self.assertEqual(r.bucket, "YAGNI",
            "ordering trap: KEEP should not steal a yagni-flagged idea")

    def test_radical_beats_research(self):
        """radical_flag fires RADICAL even when trigger absent (would fire RESEARCH)."""
        r = self.w.evaluate(_signals(radical_flag=True, trigger_present=False,
                                       llm_confidence=0.7))
        self.assertEqual(r.bucket, "RADICAL")

    def test_phase_2_beats_research_when_xl(self):
        """XL effort + no trigger: PHASE_2 should fire before RESEARCH."""
        r = self.w.evaluate(_signals(effort_bucket="XL", trigger_present=False,
                                       llm_confidence=0.7))
        self.assertEqual(r.bucket, "PHASE_2")

    # --- fallback ------------------------------------------------

    def test_fallback_quiet_zone(self):
        """Mid-confidence, no trigger, no XL — should hit RESEARCH not fallback."""
        r = self.w.evaluate(_signals(llm_confidence=0.6, trigger_present=False))
        self.assertEqual(r.bucket, "RESEARCH")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2.2: Run, expect green if rubric is correct**

```bash
python3 -m unittest tests.test_brainstorm_rubric_cases -v
```

Expected: all 12 tests pass. If a test fails, adjust either the test (assertion was wrong) or the rubric ordering (spec ambiguity). The spec's ordering rationale (§Rubric lines 199–215) is authoritative.

- [ ] **Step 2.3: Commit**

```bash
git add plugins/kaizen/tests/test_brainstorm_rubric_cases.py
git commit -m "test(brainstorm): T2 rubric-case + ordering-trap coverage (BK-012 P2)"
```

---

## Task 3: P3 — Signal computer (T3)

**Files:**
- Create: `plugins/kaizen/skills/workflow/scripts/brainstorm.py`
- Create: `plugins/kaizen/tests/test_brainstorm_signals.py`

- [ ] **Step 3.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_signals.py`:

```python
"""T3: _compute_idea_signals — pure-fn round-trip + edges."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import brainstorm  # noqa: E402


class TestBrainstormSignals(unittest.TestCase):
    def test_full_draft(self):
        s = brainstorm._compute_idea_signals({
            "idea": "When the user hits enter, then the prompt is submitted",
            "tools": ["argparse"],
            "effort_estimate": "S",
            "yagni": False,
            "radical": False,
            "confidence": 0.9,
        })
        self.assertEqual(s["length_words"], 11)
        self.assertTrue(s["has_tool_dep"])
        self.assertTrue(s["trigger_present"])
        self.assertEqual(s["effort_bucket"], "S")
        self.assertFalse(s["yagni_flag"])
        self.assertFalse(s["radical_flag"])
        self.assertAlmostEqual(s["llm_confidence"], 0.9)

    def test_empty_idea(self):
        s = brainstorm._compute_idea_signals({"idea": ""})
        self.assertEqual(s["length_words"], 0)
        self.assertFalse(s["has_tool_dep"])
        self.assertFalse(s["trigger_present"])

    def test_missing_tools_default(self):
        s = brainstorm._compute_idea_signals({"idea": "some idea text"})
        self.assertFalse(s["has_tool_dep"])

    def test_missing_effort_defaults_to_M(self):
        s = brainstorm._compute_idea_signals({"idea": "some idea"})
        self.assertEqual(s["effort_bucket"], "M")

    def test_missing_confidence_defaults_to_0_5(self):
        s = brainstorm._compute_idea_signals({"idea": "some idea"})
        self.assertAlmostEqual(s["llm_confidence"], 0.5)

    def test_trigger_arrow_unicode(self):
        s = brainstorm._compute_idea_signals({
            "idea": "user types command → kaizen dispatches handler",
        })
        self.assertTrue(s["trigger_present"])

    def test_trigger_if_then(self):
        s = brainstorm._compute_idea_signals({
            "idea": "if the user hits enter then submit the prompt",
        })
        self.assertTrue(s["trigger_present"])

    def test_pure_no_mutation(self):
        draft = {"idea": "static input text"}
        before = dict(draft)
        brainstorm._compute_idea_signals(draft)
        self.assertEqual(draft, before, "signal fn must not mutate input")

    def test_pure_deterministic(self):
        draft = {"idea": "deterministic check"}
        a = brainstorm._compute_idea_signals(draft)
        b = brainstorm._compute_idea_signals(draft)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3.2: Run, watch it fail**

```bash
python3 -m unittest tests.test_brainstorm_signals -v
```

Expected: ImportError on `import brainstorm` — module doesn't exist yet.

- [ ] **Step 3.3: Write minimal implementation (GREEN)**

Create `plugins/kaizen/skills/workflow/scripts/brainstorm.py`:

```python
"""kaizen-brainstorm — typed contract for brainstorming JSONL output.

Public surface (more added in P4-P7):

    _compute_idea_signals(draft: dict) -> dict
        Pure fn — maps an idea-draft dict to the signals dict the
        brainstorm-rubric.yaml walks. Mirrors handoff exemplar.

The full CLI (`score`), override loop, and threshold gate land in
subsequent phases of BK-012.
"""
from __future__ import annotations

import re

_TRIGGER_RE = re.compile(r"\bwhen\b|\btrigger\b|→|\bif\b.*\bthen\b", re.I)


def _compute_idea_signals(draft: dict) -> dict:
    """Map an idea-draft to the signals dict walked by brainstorm-rubric.yaml.

    Pure: no I/O, no env, no clock. Same input → same output. Does
    not mutate `draft`. Mirrors brainstorm-rubric.yaml `signal:` keys
    one-for-one (named-once discipline from decision-rubric Iron Laws).
    """
    text = draft.get("idea", "") or ""
    return {
        "length_words":    len(text.split()),
        "has_tool_dep":    bool(draft.get("tools")),
        "trigger_present": bool(_TRIGGER_RE.search(text)),
        "effort_bucket":   draft.get("effort_estimate", "M") or "M",
        "yagni_flag":      bool(draft.get("yagni", False)),
        "radical_flag":    bool(draft.get("radical", False)),
        "llm_confidence":  float(draft.get("confidence", 0.5) or 0.5),
        "novelty_score":   float(draft.get("novelty_score", 0.5) or 0.5),
    }
```

- [ ] **Step 3.4: Re-run, watch it pass**

```bash
python3 -m unittest tests.test_brainstorm_signals -v
```

Expected: 9 tests passed.

- [ ] **Step 3.5: Commit**

```bash
git add plugins/kaizen/skills/workflow/scripts/brainstorm.py \
        plugins/kaizen/tests/test_brainstorm_signals.py
git commit -m "feat(brainstorm): signal computer + T3 tests (BK-012 P3)"
```

---

## Task 4: P4 — score CLI + bin wrapper (T4)

**Files:**
- Modify: `plugins/kaizen/skills/workflow/scripts/brainstorm.py` (add `score_jsonl`, `main`, argparse)
- Create: `plugins/kaizen/bin/kaizen-brainstorm` (symlink)
- Modify: `plugins/kaizen/.claude-plugin/plugin.json` (permission entry)
- Create: `plugins/kaizen/tests/test_brainstorm_score_cli.py`

- [ ] **Step 4.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_score_cli.py`:

```python
"""T4: kaizen-brainstorm score — CLI subprocess contract.

Hits the script directly (not the bin/ symlink, to keep test paths
absolute). Subprocess boundary so we exercise argparse + envelope
emission + atomic write end-to-end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ / "skills/workflow/scripts/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"


def _run(*args, **kw):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=30, **kw,
    )


def _jsonl(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r) for r in rows) + "\n"


_FIVE_DRAFTS = [
    {"id": 1, "theme": "core",  "idea": "When the user hits enter, then submit the prompt",
     "confidence": 0.9, "effort_estimate": "S"},
    {"id": 2, "theme": "edge",  "idea": "Idle TTL knob to auto-close stale sessions",
     "confidence": 0.6, "trigger_present": False, "effort_estimate": "M"},
    {"id": 3, "theme": "moon",  "idea": "Reactive UI that rewrites itself based on user mood",
     "confidence": 0.4, "radical": True},
    {"id": 4, "theme": "trim",  "idea": "Delete cache nightly via cron",
     "confidence": 0.2, "yagni": True},
    {"id": 5, "theme": "huge",  "idea": "When traffic spikes, then shard the queue across regions",
     "confidence": 0.7, "effort_estimate": "XL"},
]


class TestBrainstormScoreCLI(unittest.TestCase):
    def test_score_enriches_every_row(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC), "--json")
            self.assertEqual(r.returncode, 0,
                f"stdout: {r.stdout}\nstderr: {r.stderr}")
            payload = json.loads(r.stdout)
            rows = payload["data"]["rows"]
            self.assertEqual(len(rows), 5)
            for row in rows:
                for field in ("auto_bucket", "classification_confidence",
                              "rationale", "rubric_version"):
                    self.assertIn(field, row, f"row {row.get('id')} missing {field}")

    def test_rewrite_atomic_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC), "--rewrite")
            self.assertEqual(r.returncode, 0, r.stderr)
            new_rows = [json.loads(ln) for ln in inp.read_text().splitlines() if ln.strip()]
            self.assertEqual(len(new_rows), 5)
            for row in new_rows:
                self.assertIn("auto_bucket", row)

    def test_max_ideas_exit_1(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--max-ideas", "3", "--json")
            self.assertEqual(r.returncode, 1)
            payload = json.loads(r.stdout)
            self.assertTrue(payload.get("errors"))

    def test_max_ideas_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text(_jsonl(_FIVE_DRAFTS))
            env = {**os.environ, "KAIZEN_BRAINSTORM_MAX_IDEAS": "3"}
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(r.returncode, 1, r.stderr)

    def test_rubric_version_drift_needs_force(self):
        """When input rows carry rubric_version != current, --rewrite without --force warns."""
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            # Pre-scored row carrying a stale rubric_version
            pre = [{**_FIVE_DRAFTS[0], "auto_bucket": "KEEP",
                    "classification_confidence": 1.0,
                    "rationale": "old",  "rubric_version": "999"}]
            inp.write_text(_jsonl(pre))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--rewrite")
            self.assertNotEqual(r.returncode, 0,
                "drift without --force should fail")
            self.assertIn("rubric_version", r.stderr + r.stdout)

    def test_rubric_version_drift_with_force_proceeds(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            pre = [{**_FIVE_DRAFTS[0], "auto_bucket": "KEEP",
                    "classification_confidence": 1.0,
                    "rationale": "old",  "rubric_version": "999"}]
            inp.write_text(_jsonl(pre))
            r = _run("score", "--input", str(inp), "--rubric", str(_RUBRIC),
                     "--rewrite", "--force")
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4.2: Run, watch it fail**

```bash
python3 -m unittest tests.test_brainstorm_score_cli -v
```

Expected: every test fails — `score` subcommand doesn't exist.

- [ ] **Step 4.3: Extend brainstorm.py with the CLI (GREEN)**

Append to `plugins/kaizen/skills/workflow/scripts/brainstorm.py`:

```python
import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402
import schema_cli  # noqa: E402
from _atomic import atomic_write  # noqa: E402

_DEFAULT_MAX_IDEAS = 250
_emit = _envelope.emitter("kaizen-brainstorm", tool_version="1.0.0")


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {i}: invalid JSON: {exc}") from exc
    return rows


def _rubric_version(rubric_path: Path) -> str:
    """Read top-level `version:` from the rubric YAML (string)."""
    import yaml
    with rubric_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return str(raw.get("version", "1"))


def score_jsonl(rows: list[dict], rubric_path: Path) -> list[dict]:
    """Enrich each row with auto_bucket / classification_confidence /
    rationale / rubric_version. Existing manual_bucket preserved."""
    walker = schema_cli.BucketWalker.from_yaml(rubric_path)
    rv = _rubric_version(rubric_path)
    out: list[dict] = []
    for row in rows:
        signals = _compute_idea_signals(row)
        try:
            result = walker.evaluate(signals)
            auto_bucket = result.bucket
            confidence = float(result.confidence)
            rationale = result.rationale
        except Exception as exc:  # defensive — rubric eval shouldn't raise
            auto_bucket = "NEEDS_AGENT"
            confidence = 0.0
            rationale = f"signal computer / rubric failed: {exc}"
        enriched = dict(row)
        enriched["auto_bucket"] = auto_bucket
        enriched["classification_confidence"] = confidence
        enriched["rationale"] = rationale
        enriched["rubric_version"] = rv
        out.append(enriched)
    return out


def _cmd_score(args) -> int:
    inp = Path(args.input).expanduser()
    rubric = Path(args.rubric).expanduser()

    if not inp.is_file():
        _emit({}, verdict="red")
        sys.stderr.write(f"[kaizen-brainstorm score] input not found: {inp}\n")
        return 1
    if not rubric.is_file():
        _emit({}, verdict="red")
        sys.stderr.write(f"[kaizen-brainstorm score] rubric not found: {rubric}\n")
        return 1

    max_ideas = int(os.environ.get("KAIZEN_BRAINSTORM_MAX_IDEAS",
                                     args.max_ideas or _DEFAULT_MAX_IDEAS))

    try:
        rows = _load_jsonl(inp)
    except ValueError as exc:
        _emit({"input": str(inp), "error": str(exc)}, verdict="red")
        return 1

    if len(rows) > max_ideas:
        _emit({"input": str(inp), "count": len(rows),
                "max_ideas": max_ideas,
                "errors": [f"{len(rows)} ideas > --max-ideas {max_ideas}"]},
               verdict="red")
        return 1

    if not rows:
        sys.stderr.write("[kaizen-brainstorm score] no ideas to score\n")
        _emit({"input": str(inp), "rows": []}, verdict="green")
        return 0

    # rubric-version drift check on --rewrite
    rv = _rubric_version(rubric)
    if args.rewrite and not args.force:
        drift_ids = [r.get("id") for r in rows
                     if "rubric_version" in r and str(r["rubric_version"]) != rv]
        if drift_ids:
            sys.stderr.write(
                f"[kaizen-brainstorm score] rubric_version drift "
                f"(current={rv}, drifting rows={drift_ids[:5]}{'...' if len(drift_ids)>5 else ''}) "
                f"— re-run with --force to overwrite\n"
            )
            return 2

    enriched = score_jsonl(rows, rubric)

    if args.rewrite:
        body = "\n".join(json.dumps(r, sort_keys=True) for r in enriched) + "\n"
        atomic_write(inp, body)

    bucket_counts: dict[str, int] = {}
    for r in enriched:
        bucket_counts[r["auto_bucket"]] = bucket_counts.get(r["auto_bucket"], 0) + 1

    _emit(
        {"input": str(inp), "rubric": str(rubric), "rows": enriched,
         "count": len(enriched), "buckets": bucket_counts,
         "rubric_version": rv},
        verdict="green", counts=bucket_counts,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-brainstorm",
        description="Typed contract for brainstorming JSONL output.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="Score a brainstorm JSONL through the rubric.")
    sc.add_argument("--input", required=True, help="Path to input JSONL.")
    sc.add_argument("--rubric", required=True, help="Path to brainstorm-rubric.yaml.")
    sc.add_argument("--rewrite", action="store_true",
        help="Atomic in-place rewrite. Default emits to stdout.")
    sc.add_argument("--force", action="store_true",
        help="Required with --rewrite when rubric_version drift detected.")
    sc.add_argument("--max-ideas", type=int, default=None,
        help=f"Hard-stop above N ideas. Default {_DEFAULT_MAX_IDEAS}; "
             f"env KAIZEN_BRAINSTORM_MAX_IDEAS overrides.")
    sc.add_argument("--json", action="store_true",
        help="No-op flag — output is always canonical envelope JSON.")
    sc.set_defaults(func=_cmd_score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4.4: Create the bin/ wrapper**

```bash
cd /home/cherry86/workspace/kaizen-md/plugins/kaizen
ln -s ../skills/workflow/scripts/brainstorm.py bin/kaizen-brainstorm
chmod +x skills/workflow/scripts/brainstorm.py
```

And ensure the script has a shebang at the very first line. Edit `brainstorm.py` to make line 1:

```python
#!/usr/bin/env python3
```

(if not already present — insert before the docstring).

- [ ] **Step 4.5: Add plugin.json permission**

Open `plugins/kaizen/.claude-plugin/plugin.json` and add to `permissions.allow` array (alphabetical order):

```json
"Bash(kaizen-brainstorm:*)",
```

(Use the existing entries' format as the template — look for the nearest `Bash(kaizen-*:*)` entry and match.)

- [ ] **Step 4.6: Re-run T4, watch it pass**

```bash
python3 -m unittest tests.test_brainstorm_score_cli -v
```

Expected: 6 tests passed.

- [ ] **Step 4.7: Commit**

```bash
git add plugins/kaizen/skills/workflow/scripts/brainstorm.py \
        plugins/kaizen/bin/kaizen-brainstorm \
        plugins/kaizen/.claude-plugin/plugin.json \
        plugins/kaizen/tests/test_brainstorm_score_cli.py
git commit -m "feat(brainstorm): score CLI + bin wrapper + T4 tests (BK-012 P4)"
```

---

## Task 5: P5 — JSON Schema (T5)

**Files:**
- Create: `plugins/kaizen/skills/brainstorming/domain/schemas/idea.schema.json`
- Modify: `plugins/kaizen/skills/workflow/scripts/brainstorm.py` (validate on write)
- Create: `plugins/kaizen/tests/test_brainstorm_schema.py`

- [ ] **Step 5.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_schema.py`:

```python
"""T5: every emitted row validates against idea.schema.json."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ / "skills/workflow/scripts/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"
_SCHEMA = _KZ / "skills/brainstorming/domain/schemas/idea.schema.json"

try:
    from jsonschema import validate as _validate
    _HAS = True
except ImportError:
    _HAS = False


_GOOD_ROWS = [
    {"id": 1, "theme": "x", "idea": "When user hits enter, then submit",
     "confidence": 0.9, "effort_estimate": "S"},
]


@unittest.skipUnless(_HAS, "jsonschema not installed")
class TestBrainstormSchema(unittest.TestCase):
    def test_schema_file_exists(self):
        self.assertTrue(_SCHEMA.is_file(), f"missing schema: {_SCHEMA}")

    def test_emitted_rows_validate(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            inp.write_text("\n".join(json.dumps(r) for r in _GOOD_ROWS) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            with _SCHEMA.open("r", encoding="utf-8") as f:
                schema = json.load(f)
            for row in json.loads(r.stdout)["data"]["rows"]:
                _validate(row, schema)  # raises on failure

    def test_required_field_missing_rejected_at_schema_check(self):
        with _SCHEMA.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        bad = {"id": 1, "theme": "x", "idea": "no confidence",
               "auto_bucket": "KEEP", "classification_confidence": 1.0,
               "rationale": "x", "rubric_version": "1"}
        # missing `confidence` (required)
        from jsonschema import ValidationError
        with self.assertRaises(ValidationError):
            _validate(bad, schema)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5.2: Run, watch it fail**

```bash
python3 -m unittest tests.test_brainstorm_schema -v
```

Expected: `missing schema` failure on test_schema_file_exists.

- [ ] **Step 5.3: Create the schema file (GREEN)**

Create `plugins/kaizen/skills/brainstorming/domain/schemas/idea.schema.json`:

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
                        "description": "Rubric's confidence in its own bucket assignment. 1.0 deterministic, confidence_threshold (0.85) when fallback."},
    "rationale":       {"type": "string"},
    "rubric_version":  {"type": "string", "description": "Matches version: in rubric YAML."},
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

- [ ] **Step 5.4: Re-run, watch it pass**

```bash
python3 -m unittest tests.test_brainstorm_schema -v
```

Expected: 3 tests passed (or skipped if jsonschema not installed; install it first via `pip install jsonschema` if needed for local).

- [ ] **Step 5.5: Commit**

```bash
git add plugins/kaizen/skills/brainstorming/domain/schemas/idea.schema.json \
        plugins/kaizen/tests/test_brainstorm_schema.py
git commit -m "feat(brainstorm): idea.schema.json + T5 validation (BK-012 P5)"
```

---

## Task 6: P6 — Override loop (T6 + T6b)

**Files:**
- Modify: `plugins/kaizen/skills/workflow/scripts/brainstorm.py` (`run_override_loop`)
- Create: `plugins/kaizen/tests/test_brainstorm_override.py`

The override loop reads enriched rows + presents NEEDS_AGENT items to the user via `AskUserQuestion`. In tests we mock the function; in scripted runs the `KAIZEN_BRAINSTORM_BATCH=1` env skips the prompt entirely.

- [ ] **Step 6.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_override.py`:

```python
"""T6 + T6b: override loop preserves auto_bucket, batch env skips ask,
re-score never touches existing manual_bucket."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import brainstorm  # noqa: E402

_SCRIPT = _KZ / "skills/workflow/scripts/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"


class TestBrainstormOverride(unittest.TestCase):
    def test_manual_bucket_set_preserves_auto(self):
        rows = [{"id": 1, "theme": "x", "idea": "When X then Y something",
                 "confidence": 0.9, "manual_bucket": "RADICAL"}]
        out = brainstorm.score_jsonl(rows, _RUBRIC)
        self.assertEqual(out[0].get("auto_bucket"), "KEEP")
        self.assertEqual(out[0].get("manual_bucket"), "RADICAL")

    def test_rewrite_preserves_existing_manual_bucket(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            row = {"id": 1, "theme": "x", "idea": "When X then Y something",
                   "confidence": 0.9, "manual_bucket": "RADICAL"}
            inp.write_text(json.dumps(row) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--rewrite"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            new = json.loads(inp.read_text().splitlines()[0])
            self.assertEqual(new["manual_bucket"], "RADICAL")

    def test_empty_jsonl_no_op(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "empty.jsonl"
            inp.write_text("")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["data"]["rows"], [])

    def test_batch_env_skips_ask(self):
        """KAIZEN_BRAINSTORM_BATCH=1 → run_override_loop is a no-op."""
        rows = [{"id": 1, "theme": "x", "idea": "short",
                 "auto_bucket": "NEEDS_AGENT", "classification_confidence": 0.85,
                 "rationale": "len<8", "rubric_version": "1"}]
        env_was = os.environ.get("KAIZEN_BRAINSTORM_BATCH")
        os.environ["KAIZEN_BRAINSTORM_BATCH"] = "1"
        try:
            out = brainstorm.run_override_loop(rows, ask_user_question=None)
            self.assertEqual(out, rows)  # untouched
        finally:
            if env_was is None:
                del os.environ["KAIZEN_BRAINSTORM_BATCH"]
            else:
                os.environ["KAIZEN_BRAINSTORM_BATCH"] = env_was

    def test_mocked_ask_propagates_manual_bucket(self):
        """T6b: mocked AskUserQuestion returns fixed bucket → row picks it up."""
        rows = [{"id": 7, "theme": "x", "idea": "short",
                 "auto_bucket": "NEEDS_AGENT", "classification_confidence": 0.85,
                 "rationale": "len<8", "rubric_version": "1"}]
        mock_ask = mock.MagicMock(return_value={"7": "RESEARCH"})
        out = brainstorm.run_override_loop(rows, ask_user_question=mock_ask)
        self.assertEqual(out[0].get("manual_bucket"), "RESEARCH")
        self.assertEqual(out[0]["auto_bucket"], "NEEDS_AGENT")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6.2: Run, watch the new ones fail**

```bash
python3 -m unittest tests.test_brainstorm_override -v
```

Expected: `run_override_loop` doesn't exist → AttributeError. The first three tests may pass already from earlier code paths.

- [ ] **Step 6.3: Add `run_override_loop` to brainstorm.py (GREEN)**

Append to `plugins/kaizen/skills/workflow/scripts/brainstorm.py` (above `_cmd_score`):

```python
def run_override_loop(rows: list[dict],
                      *, ask_user_question=None) -> list[dict]:
    """Surface NEEDS_AGENT rows for manual bucketing.

    `ask_user_question` is the injection point — the production code
    plugs in the actual AskUserQuestion call; tests mock it to a fn
    that returns a {id_str: bucket_str} dict.

    Scripted runs set KAIZEN_BRAINSTORM_BATCH=1 to skip the prompt —
    NEEDS_AGENT rows pass through with manual_bucket unset.
    """
    if os.environ.get("KAIZEN_BRAINSTORM_BATCH") == "1":
        needs = sum(1 for r in rows if r.get("auto_bucket") == "NEEDS_AGENT")
        if needs:
            sys.stderr.write(
                f"[kaizen-brainstorm] BATCH=1: {needs} NEEDS_AGENT rows "
                f"left without manual_bucket\n"
            )
        return rows
    needs_agent = [r for r in rows if r.get("auto_bucket") == "NEEDS_AGENT"]
    if not needs_agent or ask_user_question is None:
        return rows
    picks = ask_user_question(needs_agent) or {}
    out = []
    for r in rows:
        rid = str(r.get("id"))
        if rid in picks:
            r = dict(r)
            r["manual_bucket"] = picks[rid]
        out.append(r)
    return out
```

- [ ] **Step 6.4: Re-run, watch all pass**

```bash
python3 -m unittest tests.test_brainstorm_override -v
```

Expected: 5 tests passed.

- [ ] **Step 6.5: Commit**

```bash
git add plugins/kaizen/skills/workflow/scripts/brainstorm.py \
        plugins/kaizen/tests/test_brainstorm_override.py
git commit -m "feat(brainstorm): override loop + BATCH env + T6 tests (BK-012 P6)"
```

---

## Task 7: P7 — Skill flow + SKILL.md threshold gate (T7)

**Files:**
- Modify: `plugins/kaizen/skills/brainstorming/SKILL.md` (+§Threshold-gated output contract)
- Modify: `plugins/kaizen/skills/workflow/scripts/brainstorm.py` (threshold helper)
- Create: `plugins/kaizen/tests/test_brainstorm_skill_flow.py`

The skill body documents the contract; the threshold check is a pure-fn helper consumers (the SKILL agent loop) call to decide whether to emit JSONL.

- [ ] **Step 7.1: Write the failing test**

Create `plugins/kaizen/tests/test_brainstorm_skill_flow.py`:

```python
"""T7: threshold-gated emission. Under threshold (default 10) → prose-only,
over threshold → JSONL emit."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import brainstorm  # noqa: E402


class TestBrainstormSkillFlow(unittest.TestCase):
    def test_should_emit_jsonl_under_threshold_false(self):
        self.assertFalse(brainstorm.should_emit_jsonl(5))
        self.assertFalse(brainstorm.should_emit_jsonl(10))  # ≤10 = prose only

    def test_should_emit_jsonl_over_threshold_true(self):
        self.assertTrue(brainstorm.should_emit_jsonl(15))
        self.assertTrue(brainstorm.should_emit_jsonl(11))

    def test_should_emit_jsonl_empty_false(self):
        self.assertFalse(brainstorm.should_emit_jsonl(0))

    def test_threshold_override(self):
        self.assertTrue(brainstorm.should_emit_jsonl(8, threshold=5))
        self.assertFalse(brainstorm.should_emit_jsonl(4, threshold=5))

    def test_skill_md_has_threshold_section(self):
        skill = _KZ / "skills/brainstorming/SKILL.md"
        body = skill.read_text(encoding="utf-8")
        self.assertIn("Threshold-gated output contract", body)
        self.assertIn("idea.schema.json", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7.2: Run, watch it fail**

```bash
python3 -m unittest tests.test_brainstorm_skill_flow -v
```

Expected: AttributeError on `should_emit_jsonl` + SKILL.md missing the section.

- [ ] **Step 7.3: Add `should_emit_jsonl` to brainstorm.py (GREEN)**

Append to `brainstorm.py` (with the other helpers):

```python
_DEFAULT_THRESHOLD = 10


def should_emit_jsonl(idea_count: int, *, threshold: int = _DEFAULT_THRESHOLD) -> bool:
    """True when brainstorm has > threshold ideas (default 10).

    Pure fn. Empty brainstorms (0 ideas) always return False (no-op,
    not an error). Under-threshold means prose-only narration."""
    return idea_count > threshold
```

- [ ] **Step 7.4: Append the Threshold-gated section to SKILL.md**

Read current SKILL.md tail, then append (use Edit if section anchor exists, else Write the append). New section content:

```markdown

## Threshold-gated output contract

For brainstorms with **>10 ideas** (configurable: `--threshold N`), the
skill emits a typed JSONL alongside the prose spec:

  plans/<date>-<topic>.jsonl    structured per-idea records
  plans/<date>-<topic>.md       narrative spec (existing)

Each idea row validates against
`plugins/kaizen/skills/brainstorming/domain/schemas/idea.schema.json`
and carries:

- `auto_bucket` — assigned by `brainstorm-rubric.yaml` via
  `schema_cli.BucketWalker` (KEEP / YAGNI / RADICAL / PHASE_2 /
  RESEARCH / NEEDS_AGENT)
- `confidence` — 0.0–1.0, LLM self-rated input per-idea
- `classification_confidence` — 0.0–1.0, rubric-emitted output
  (1.0 deterministic, 0.85 fallback)
- `rationale` — one-line justification from the rubric walker
- `rubric_version` — matches the rubric YAML's `version:` key
- `manual_bucket` — user override from the batch-confirm step
  (null if no override)

Brainstorms **≤10 ideas** → prose-narration only (no JSONL).
Empty brainstorms (0 ideas) → no-op; stderr `"no ideas to score"`.

Scripted / CI runs set `KAIZEN_BRAINSTORM_BATCH=1` to skip the
`AskUserQuestion` override loop. `NEEDS_AGENT` rows emit with
`manual_bucket = null` and a STDERR warning naming the count.

CLI: `kaizen-brainstorm score --input PATH --rubric PATH [--rewrite] [--force]`.
```

- [ ] **Step 7.5: Re-run, watch it pass**

```bash
python3 -m unittest tests.test_brainstorm_skill_flow -v
```

Expected: 5 tests passed.

- [ ] **Step 7.6: Commit**

```bash
git add plugins/kaizen/skills/workflow/scripts/brainstorm.py \
        plugins/kaizen/skills/brainstorming/SKILL.md \
        plugins/kaizen/tests/test_brainstorm_skill_flow.py
git commit -m "feat(brainstorm): threshold-gate helper + SKILL.md contract (BK-012 P7)"
```

---

## Task 8: P8 — Ollama live test (T8, graceful-skip)

**Files:**
- Create: `plugins/kaizen/tests/test_brainstorm_ollama_live.py`

This test exercises the `score` CLI against synthetic ideas pre-flagged with `yagni`/`radical` so we can assert the flag signals propagate to the right buckets. The LLM call is opt-in and skips when unavailable — matching `test_gold_mine_ollama_live.py`'s shape.

- [ ] **Step 8.1: Write the test (acts as both RED-and-GREEN since it depends on existing CLI)**

Create `plugins/kaizen/tests/test_brainstorm_ollama_live.py`:

```python
"""T8: Live smoke against local Ollama (granite4.1:8b).

Skipped when:
  - KAIZEN_BRAINSTORM_TEST_LIVE != "1" (opt-in)
  - Ollama not reachable at :11434
  - granite4.1:8b not present
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ / "skills/workflow/scripts/brainstorm.py"
_RUBRIC = _KZ / "skills/brainstorming/domain/brainstorm-rubric.yaml"


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                      timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _granite_present() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                      timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in data.get("models", [])]
            return any(n.startswith("granite4.1:8b") for n in names)
    except Exception:
        return False


_LIVE = os.environ.get("KAIZEN_BRAINSTORM_TEST_LIVE", "") == "1"
_REACHABLE = _ollama_reachable() if _LIVE else False
_GRANITE = _granite_present() if _LIVE else False

_SKIP_MSG = (
    f"live test gated: opt_in={_LIVE}, "
    f"ollama_reachable={_REACHABLE}, granite_present={_GRANITE}"
)


@unittest.skipUnless(_LIVE and _REACHABLE and _GRANITE, _SKIP_MSG)
class TestBrainstormOllamaLive(unittest.TestCase):
    """Flags-propagate test — uses pre-flagged synthetic ideas; no real LLM
    call in the contract. The 'live' label means Ollama-stack is available;
    the actual assertion is that the deterministic rubric still classifies
    flag-driven ideas correctly when run in a realistic stack."""

    def test_yagni_flag_routes_to_yagni_bucket(self):
        rows = [
            {"id": 1, "theme": "live", "idea": "delete logs nightly via cron job",
             "confidence": 0.9, "yagni": True},
        ]
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "live.jsonl"
            inp.write_text(json.dumps(rows[0]) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads(r.stdout)["data"]["rows"][0]
            self.assertEqual(row["auto_bucket"], "YAGNI")

    def test_radical_flag_routes_to_radical_bucket(self):
        rows = [
            {"id": 2, "theme": "live", "idea": "rewrite the planet using neuromorphic chips",
             "confidence": 0.7, "radical": True},
        ]
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "live.jsonl"
            inp.write_text(json.dumps(rows[0]) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads(r.stdout)["data"]["rows"][0]
            self.assertEqual(row["auto_bucket"], "RADICAL")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8.2: Run (will skip in normal CI)**

```bash
python3 -m unittest tests.test_brainstorm_ollama_live -v
```

Expected: SKIPPED (live test gated). Set `KAIZEN_BRAINSTORM_TEST_LIVE=1` locally if you have granite4.1:8b pulled to verify.

- [ ] **Step 8.3: Commit**

```bash
git add plugins/kaizen/tests/test_brainstorm_ollama_live.py
git commit -m "test(brainstorm): T8 Ollama-gated live smoke (BK-012 P8)"
```

---

## Task 9: P9 — Full regression + report + park Phase-2 deferrals

**Files:**
- Park entries in `.kaizen/workflow/backlog.json` via `kaizen backlog add` + `park`

- [ ] **Step 9.1: Run the full plugin suite**

```bash
cd /home/cherry86/workspace/kaizen-md/plugins/kaizen
python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -10
```

Expected: 0 failures. Note new test count — should be ~50 added (8 files × ~5-12 tests each).

- [ ] **Step 9.2: Run the end-to-end smoke pipeline**

```bash
bash skills/workflow/scripts/test-pipeline.sh 2>&1 | tail -20
```

Expected: TAP all-green.

- [ ] **Step 9.3: Park Phase-2 deferrals**

```bash
kaizen backlog add \
  --title "Brainstorm signal: novelty_score (Jaccard idea-overlap)" \
  --probe "Spec 2026-05-18-brainstorming-confidence-score-design.md §Phase 2 deferrals row 3 — trigger: first duplicate-idea complaint or rubric-tuning evidence" \
  --section parked

kaizen backlog add \
  --title "kaizen-brainstorm stats subcommand (bucket distribution drift)" \
  --probe "Spec 2026-05-18-brainstorming-confidence-score-design.md §Phase 2 deferrals row 16 — trigger: bucket distribution shifts ≥20% across 3 brainstorms" \
  --section parked

kaizen backlog add \
  --title "Pre-commit gate nudge: *-brainstorm.md without sibling .jsonl" \
  --probe "Spec 2026-05-18-brainstorming-confidence-score-design.md §Phase 2 deferrals row 18 — trigger: first real 'I forgot to score it' incident" \
  --section parked
```

- [ ] **Step 9.4: Log the architecture row (gate-required)**

Append a row to `.kaizen/workflow/progress.md` summarizing the BK-012 landing (8 phases / new file inventory / test counts).

- [ ] **Step 9.5: Commit P9 housekeeping**

```bash
git add .kaizen/workflow/backlog.json .kaizen/workflow/backlog.md \
        .kaizen/workflow/progress.md
git commit -m "chore(backlog): park BK-012 Phase-2 deferrals + log architecture row"
```

- [ ] **Step 9.6: Final report**

Emit a summary matching the tdd skill's Phase-5 format:

```
## TDD Complete: brainstorming confidence-score (BK-012)

### Coverage
- Unit: ~ (T1 lint, T2 rubric cases, T3 signals, T5 schema, T7 threshold)
- Integration: ~ (T4 CLI subprocess, T6 override loop)
- Regression: full suite + test-pipeline.sh
- EDD: not applicable (no LLM emission in CLI itself; T8 is a stack smoke)

### Files
- New: brainstorm.py, brainstorm-rubric.yaml, idea.schema.json,
       bin/kaizen-brainstorm, 8 test files
- Modified: brainstorming/SKILL.md, plugin.json (permissions)

### Backlog
- BK-012 ticked
- BK-015/16/17 parked (Phase-2 deferrals)

### Outcome
- Test count: <before> → <after> (+N new)
- Existing suite: <X> passed, 0 failed
```

---

## Self-Review checklist

Before handing off:

**Spec coverage** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| §Architecture (signal → rubric → emit) | P3 (signal) + P4 (emit) + P1 (rubric YAML) |
| §Components.Signal computer | P3 |
| §Components.Rubric | P1 + P2 |
| §Components.Override loop | P6 |
| §Components.`kaizen-brainstorm score` CLI | P4 |
| §Components.JSON Schema | P5 |
| §Components.SKILL.md update | P7 |
| §Threshold-gated output contract | P7 |
| §Error handling table | P4 (max-ideas, rubric load, write failure), P6 (cancel + BATCH), P5 (schema reject) |
| §Testing — 8 test layers | P1-P8 (one-to-one) |
| §File layout | All phases assemble |
| §Phase 2 deferrals | P9 (parked, not implemented) |
| §Back-compat / migration | P4 (`--rewrite` preserves manual_bucket per P6) |
| §Open questions | Resolved in plan header |

**Placeholder scan** — no TODO / TBD / "implement later" in any step. Every step has executable content.

**Type consistency** — `_compute_idea_signals` keys match `brainstorm-rubric.yaml` `signal:` keys exactly (length_words, has_tool_dep, trigger_present, effort_bucket, yagni_flag, radical_flag, llm_confidence, novelty_score). `auto_bucket` enum values consistent across YAML, schema, and tests. `classification_confidence` (not `confidence`) is the schema field name for rubric output.

**Iron-laws alignment:**
- bin-wrapper-per-cli ✓ (P4 creates `bin/kaizen-brainstorm`)
- plugin-manifest-permissions ✓ (P4 adds the permission)
- paired-tests ✓ (every new script + skill change has a sibling test file across P1-P8)
- schema-driven domain yaml ✓ (P1 + P5)
