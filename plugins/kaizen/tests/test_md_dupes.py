"""md-dupes (idea #9): duplicate heading sections within one file."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import md_dupes  # noqa: E402


class TestMdDupes(unittest.TestCase):
    def test_dupe_flagged(self):
        text = "## Setup\nstuff\n\n## Notes\nx\n\n## Setup\nmore\n"
        f = md_dupes.scan_text(text, path="a.md")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["heading"], "Setup")

    def test_unique_headings_ok(self):
        text = "## A\n## B\n## C\n"
        self.assertEqual(md_dupes.scan_text(text, path="a.md"), [])


if __name__ == "__main__":
    unittest.main()
