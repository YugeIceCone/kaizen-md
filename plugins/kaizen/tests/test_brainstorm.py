"""T3: _compute_idea_signals — pure-fn round-trip + edges."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

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
        self.assertEqual(s["length_words"], 10)
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
