"""Tests for /kaizen:mode slash command — structural + content."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/mode.md"


class TestCommandFile(unittest.TestCase):
    def test_command_file_exists(self):
        self.assertTrue(_CMD.is_file(), f"missing: {_CMD}")


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")
        # Split frontmatter
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", self.text, re.DOTALL)
        self.assertIsNotNone(m, "no YAML frontmatter")
        self.fm = m.group(1)
        self.body = m.group(2)

    def test_name_is_mode(self):
        self.assertIn("name: mode", self.fm)

    def test_argument_hint_lists_three_modes(self):
        self.assertIn("argument-hint:", self.fm)
        self.assertIn("loop", self.fm)
        self.assertIn("workflow", self.fm)
        self.assertIn("neither", self.fm)

    def test_allowed_tools_grants_bin_and_askuser(self):
        self.assertIn("kaizen-session-mode", self.fm)
        self.assertIn("AskUserQuestion", self.fm)

    def test_no_default_spaces_in_arguments_pattern(self):
        """Iron-law: $ARGUMENTS must not use a ${ARGUMENTS:-default with
        spaces} pattern (matches plugin-dev iron-law spec)."""
        self.assertNotRegex(self.body, r"\$\{ARGUMENTS:-[^}]* [^}]*\}")


class TestBodyContent(unittest.TestCase):
    def setUp(self):
        self.body = _CMD.read_text(encoding="utf-8")

    def test_body_references_all_4_bundles(self):
        for bundle in ("Simplicity", "Structure", "Process", "Karpathy"):
            self.assertIn(bundle, self.body,
                          f"body missing {bundle!r} bundle option")

    def test_body_references_operational_bundles(self):
        """New operational tier — Quality / Security / Brain hygiene / Plugin-dev."""
        for bundle in ("Quality", "Security", "Brain hygiene", "Plugin-dev"):
            self.assertIn(bundle, self.body,
                          f"body missing {bundle!r} operational bundle option")

    def test_body_references_work_mode_bundles(self):
        """Work-mode tier — Discovery / Debugging / Refactoring / Planning."""
        for bundle in ("Discovery", "Debugging", "Refactoring", "Planning"):
            self.assertIn(bundle, self.body,
                          f"body missing {bundle!r} work-mode bundle option")

    def test_body_prescribes_kaizen_session_mode_set(self):
        self.assertIn("kaizen-session-mode set", self.body)
        self.assertIn("--bundles", self.body)

    def test_body_handles_three_arg_branches(self):
        """Doc covers: known-mode arg, empty arg, invalid arg."""
        self.assertIn("empty", self.body.lower())
        self.assertIn("invalid", self.body.lower())

    def test_body_includes_threshold_options(self):
        """Q2 (threshold) must list all 4 % choices + Disabled."""
        for pct in ("25%", "50%", "75%", "85%"):
            self.assertIn(pct, self.body)
        self.assertIn("Disabled", self.body)
        self.assertIn("--threshold", self.body)

    def test_body_references_bundle_name_lowercase_mapping(self):
        # Agent needs to know which label → which lowercased bundle id
        for lc in ("simplicity", "structure", "process", "karpathy",
                    "quality", "security", "brain-hygiene", "plugin-dev",
                    "discovery", "debugging", "refactoring", "planning"):
            self.assertIn(lc, self.body,
                          f"body missing lowercase bundle id {lc!r}")


if __name__ == "__main__":
    unittest.main()
