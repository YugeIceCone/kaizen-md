"""md-whitespace (idea #8): trailing whitespace / mixed indent scan in markdown."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import md_whitespace  # noqa: E402


class TestMdWhitespace(unittest.TestCase):
    def test_trailing_whitespace_flagged(self):
        f = md_whitespace.scan_text("ok\nbad   \nclean\n", path="a.md")
        rules = {x["rule"] for x in f}
        self.assertIn("trailing-whitespace", rules)

    def test_tabs_flagged(self):
        f = md_whitespace.scan_text("line\n\tindented with tab\n", path="a.md")
        rules = {x["rule"] for x in f}
        self.assertIn("tab-indent", rules)

    def test_clean_file_no_findings(self):
        f = md_whitespace.scan_text("# Title\n\nClean text.\n", path="a.md")
        self.assertEqual(f, [])


if __name__ == "__main__":
    unittest.main()
