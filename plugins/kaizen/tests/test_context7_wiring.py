"""Guard: the research->review pipeline skills name Context7 as the
first-choice doc source (regression guard — keeps the wiring from
silently disappearing on a future edit)."""
from __future__ import annotations

import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
PIPELINE = ["research", "analyze", "create-plan", "review", "validate"]


class TestContext7Wiring(unittest.TestCase):
    def test_pipeline_skills_reference_context7(self):
        missing = []
        for name in PIPELINE:
            text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            if "context7" not in text.lower():
                missing.append(name)
        self.assertEqual(
            missing, [],
            f"these pipeline skills must reference Context7: {missing}")


if __name__ == "__main__":
    unittest.main()
