"""Tests for /kaizen:loop slash command — auto-honor session-mode."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/loop.md"


class TestSessionModeAutoHonor(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_command_file_exists(self):
        self.assertTrue(_CMD.is_file())

    def test_body_mentions_auto_honor_section(self):
        """Body must instruct agent to read session-mode before composing."""
        self.assertIn("Auto-honor session-mode", self.text)
        self.assertIn("kaizen-session-mode get", self.text)

    def test_body_handles_mode_loop_case(self):
        self.assertIn('mode == "loop"', self.text)
        self.assertIn("pinned disciplines", self.text)

    def test_body_handles_mode_workflow_or_neither_case(self):
        self.assertIn('mode == "workflow"', self.text)
        self.assertIn('"neither"', self.text)
        self.assertIn("Confirm with the user", self.text)

    def test_body_handles_no_session_mode_case(self):
        self.assertIn("no session-mode is set", self.text)

    def test_body_references_threshold_handoff_contract(self):
        """Body should note that --threshold fires independently."""
        self.assertIn("--threshold", self.text)
        self.assertIn("auto-handoff", self.text.lower())

    def test_allowed_tools_includes_session_mode_bin(self):
        fm = re.match(r"^---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(fm)
        self.assertIn("kaizen-session-mode", fm.group(1))


if __name__ == "__main__":
    unittest.main()
