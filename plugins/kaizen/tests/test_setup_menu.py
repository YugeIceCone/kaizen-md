"""Contract tests for /kaizen:setup menu QA pattern.

Pins the AskUserQuestion-driven interactive flow added to setup.md.
If the structure drifts (questions missing, arg-mapping wrong,
allowed-tools missing AskUserQuestion), this test fires.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/setup.md"


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()
        self.fm = _frontmatter(self.text)

    def test_setup_command_present(self):
        self.assertTrue(_CMD.is_file())

    def test_name_is_setup(self):
        self.assertIn("name: setup", self.fm)

    def test_allowed_tools_includes_AskUserQuestion(self):
        self.assertIn("AskUserQuestion", self.fm,
                       "menu requires AskUserQuestion in allowed-tools")

    def test_allowed_tools_includes_setup_sh_dispatch(self):
        self.assertIn("setup.sh", self.fm,
                       "args-mode dispatch must stay permitted")

    def test_description_mentions_interactive_menu(self):
        self.assertIn("interactive", self.fm.lower())
        self.assertIn("menu", self.fm.lower())

    def test_argument_hint_documents_empty_means_menu(self):
        self.assertIn("empty", self.fm.lower())
        self.assertIn("menu", self.fm.lower())


class TestMenuStructure(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_4_questions_documented(self):
        """Per the AskUserQuestion 4-question ceiling, the body
        documents exactly 4 questions."""
        # Count "### Question N" headers
        questions = re.findall(r"### Question (\d+)", self.text)
        self.assertEqual(sorted(questions), ["1", "2", "3", "4"],
                          f"expected 4 numbered questions; got {questions}")

    def test_q1_action_options_present(self):
        """Q1 = top-level action picker with 4 options."""
        # Check the labels (less brittle than option ordering)
        for label in ("Install", "Uninstall", "Cache stats", "Health-check"):
            self.assertIn(label, self.text, f"Q1 missing option: {label}")

    def test_q2_scope_options_present(self):
        for label in ("Project only", "Project + global stack", "Globals only"):
            self.assertIn(label, self.text)

    def test_q3_addons_uses_multiselect(self):
        """Q3 must declare multiSelect: true since add-ons aren't mutually exclusive."""
        # The Q3 block contains 'multiSelect: true'
        q3_section = self.text.split("### Question 3")[1].split("### Question 4")[0]
        self.assertIn("multiSelect: true", q3_section,
                       "Q3 (Add-ons) must be multiSelect: true")

    def test_q4_dry_run_options_present(self):
        for label in ("Yes (recommended)", "No — apply now"):
            self.assertIn(label, self.text)

    def test_arg_assembly_table_present(self):
        """The body must document how answers map to setup.sh flags."""
        self.assertIn("Arg assembly", self.text)
        # Spot-check a few flag mappings
        for flag in ("--enable-all", "--with-index", "--with-browser",
                      "--with-daemon", "--with-trace-proxy", "--dry-run"):
            self.assertIn(flag, self.text, f"arg-assembly missing flag: {flag}")


class TestBackcompat(unittest.TestCase):
    """The args-mode dispatch must still work — args-mode is the
    canonical CLI for scripts/CI; menu is for humans."""

    def test_setup_sh_exec_block_present(self):
        text = _CMD.read_text()
        self.assertIn("setup.sh $ARGUMENTS", text,
                       "args-mode dispatch (top-of-file ! block) must remain")

    def test_existing_subcommands_still_documented(self):
        text = _CMD.read_text()
        for sub in ("install", "uninstall", "cache"):
            self.assertIn(f"/kaizen:setup {sub}", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
