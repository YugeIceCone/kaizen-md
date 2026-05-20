"""test-name-quality (idea #12): test_* methods should follow test_<X>_<scenario>."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import tname_quality  # noqa: E402

class TestTestNameQuality(unittest.TestCase):
    def test_too_short_flagged(self):
        src = "class T:\n    def test_x(self): pass\n"
        f = tname_quality.scan_text(src, path="bad.py")
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["rule"], "test-name-too-short")

    def test_ok_name(self):
        src = "class T:\n    def test_parser_handles_empty_input(self): pass\n"
        self.assertEqual(tname_quality.scan_text(src, path="ok.py"), [])

    def test_non_test_methods_ignored(self):
        src = "class T:\n    def helper(self): pass\n"
        self.assertEqual(tname_quality.scan_text(src, path="ok.py"), [])

if __name__ == "__main__":
    unittest.main()
