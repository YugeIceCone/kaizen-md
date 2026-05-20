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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/rules"))

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
        """radical_flag fires RADICAL even when trigger absent."""
        r = self.w.evaluate(_signals(radical_flag=True, trigger_present=False,
                                       llm_confidence=0.7))
        self.assertEqual(r.bucket, "RADICAL")

    def test_phase_2_beats_research_when_xl(self):
        """XL effort + no trigger: PHASE_2 should fire before RESEARCH."""
        r = self.w.evaluate(_signals(effort_bucket="XL", trigger_present=False,
                                       llm_confidence=0.7))
        self.assertEqual(r.bucket, "PHASE_2")

    # --- mid-confidence research path ----------------------------

    def test_mid_confidence_no_trigger_hits_research(self):
        r = self.w.evaluate(_signals(llm_confidence=0.6, trigger_present=False))
        self.assertEqual(r.bucket, "RESEARCH")

if __name__ == "__main__":
    unittest.main()
