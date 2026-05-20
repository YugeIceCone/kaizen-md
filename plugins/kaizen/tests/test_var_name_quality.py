"""var-name-quality (idea #13): single-letter variables at module scope flagged."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import var_name_quality  # noqa: E402

class TestVarNameQuality(unittest.TestCase):
    def test_single_letter_module_var_flagged(self):
        src = "x = 1\ny = 2\n"
        f = var_name_quality.scan_text(src, path="bad.py")
        self.assertEqual(len(f), 2)

    def test_underscore_private_ok(self):
        src = "_x = 1\n"
        self.assertEqual(var_name_quality.scan_text(src, path="ok.py"), [])

    def test_descriptive_name_ok(self):
        src = "user_count = 10\n"
        self.assertEqual(var_name_quality.scan_text(src, path="ok.py"), [])

    def test_local_in_function_ignored(self):
        src = "def f():\n    x = 1\n    return x\n"
        self.assertEqual(var_name_quality.scan_text(src, path="ok.py"), [])

if __name__ == "__main__":
    unittest.main()
