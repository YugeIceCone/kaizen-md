"""Contract tests for /kaizen:audit:axis multi-pick menu.

The audit:axis command now supports a multiSelect AskUserQuestion
checklist on empty-args invocation — pick any subset of axes
(coverage / schema-coverage / name-quality / frontmatter) to audit
in one pass. Pins the structure.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/audit/axis.md"


class TestArtifact(unittest.TestCase):
    def test_command_file_present(self):
        self.assertTrue(_CMD.is_file())


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        text = _CMD.read_text()
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        self.fm = m.group(1) if m else ""
        self.body = text

    def test_allowed_tools_includes_AskUserQuestion(self):
        self.assertIn("AskUserQuestion", self.fm)

    def test_description_mentions_checklist(self):
        self.assertTrue(
            "checklist" in self.fm.lower() or "multiSelect" in self.fm
            or "multi-axis" in self.fm.lower(),
            "description must mention the multi-pick menu pattern",
        )

    def test_argument_hint_documents_empty_means_menu(self):
        self.assertIn("empty", self.fm.lower())


class TestMenuStructure(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_multiselect_true_declared(self):
        """The picker MUST be multiSelect: true — axes can be combined."""
        self.assertIn("multiSelect: true", self.text)

    def test_all_four_pickable_axes_present(self):
        """coverage / schema-coverage / name-quality / frontmatter
        all available as options."""
        # Look in the AskUserQuestion options section
        menu_section = (self.text.split("Interactive multi-axis checklist")[1]
                         if "Interactive multi-axis checklist" in self.text
                         else self.text)
        for axis in ("coverage", "schema-coverage", "name-quality", "frontmatter"):
            self.assertIn(f'label: "{axis}"', menu_section,
                            f"missing menu option for axis: {axis}")

    def test_token_bloat_omitted_from_menu_with_reason(self):
        """token-bloat uses a different verb (`scan`); doc explains
        why it's not in the multi-pick."""
        menu_section = self.text.split("multiSelect: true")[1].split("###")[0]
        self.assertNotIn('label: "token-bloat"', menu_section,
                          "token-bloat shouldn't be a multi-pick option")
        # But the explanation must be present
        self.assertIn("token-bloat", self.text.lower())
        self.assertIn("scan", self.text.lower())

    def test_collation_format_documented(self):
        """The doc must show how to roll up per-axis results."""
        self.assertIn("multi-axis audit", self.text)


class TestBackcompat(unittest.TestCase):
    """Existing args-mode invocation must still work."""

    def test_audit_sh_axis_dispatch_remains(self):
        text = _CMD.read_text()
        self.assertIn("audit.sh axis ${ARGUMENTS:-list}", text)

    def test_axis_table_still_documents_all_5(self):
        text = _CMD.read_text()
        for axis in ("coverage", "schema-coverage", "name-quality",
                      "frontmatter", "token-bloat"):
            self.assertIn(f"`{axis}`", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
