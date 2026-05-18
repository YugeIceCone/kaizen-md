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
