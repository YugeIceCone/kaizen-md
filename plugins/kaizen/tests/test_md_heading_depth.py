"""md-heading-depth (idea #7): heading depth should not skip levels."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import md_heading_depth  # noqa: E402


class TestMdHeadingDepth(unittest.TestCase):
    def test_skipped_level_flagged(self):
        text = "# Top\n\n### Skipped\n"
        f = md_heading_depth.scan_text(text, path="bad.md")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["from"], 1)
        self.assertEqual(f[0]["to"], 3)

    def test_sequential_depth_ok(self):
        text = "# T\n## A\n### B\n## C\n"
        f = md_heading_depth.scan_text(text, path="ok.md")
        self.assertEqual(f, [])

    def test_no_headings_ok(self):
        f = md_heading_depth.scan_text("no headings here\n", path="ok.md")
        self.assertEqual(f, [])


if __name__ == "__main__":
    unittest.main()
