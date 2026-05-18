"""test-name-quality (idea #12): test_* methods should follow test_<X>_<scenario>."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import test_name_quality  # noqa: E402


class TestTestNameQuality(unittest.TestCase):
    def test_too_short_flagged(self):
        src = "class T:\n    def test_x(self): pass\n"
        f = test_name_quality.scan_text(src, path="bad.py")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["rule"], "test-name-too-short")

    def test_ok_name(self):
        src = "class T:\n    def test_parser_handles_empty_input(self): pass\n"
        self.assertEqual(test_name_quality.scan_text(src, path="ok.py"), [])

    def test_non_test_methods_ignored(self):
        src = "class T:\n    def helper(self): pass\n"
        self.assertEqual(test_name_quality.scan_text(src, path="ok.py"), [])


if __name__ == "__main__":
    unittest.main()
