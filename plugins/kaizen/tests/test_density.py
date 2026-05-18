"""test-density (idea #20): public-function count per script vs paired-test count."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import density  # noqa: E402


class TestTestDensity(unittest.TestCase):
    def test_count_public_functions(self):
        src = "def pub_one(): pass\ndef _priv(): pass\ndef pub_two(): pass\n"
        self.assertEqual(density._public_funcs(src), 2)

    def test_count_test_methods(self):
        src = "class T:\n    def test_a(self): pass\n    def test_b(self): pass\n    def helper(self): pass\n"
        self.assertEqual(density._test_methods(src), 2)

    def test_synthetic_density(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "skills/workflow/scripts").mkdir(parents=True)
            (root / "tests").mkdir(parents=True)
            (root / "skills/workflow/scripts/foo.py").write_text(
                "def a(): pass\ndef b(): pass\ndef c(): pass\n")
            (root / "tests/test_foo.py").write_text(
                "class T:\n    def test_a(self): pass\n")
            rep = density.scan(plugin_root=root)
            self.assertEqual(rep["per_script"][0]["script"], "foo.py")
            self.assertEqual(rep["per_script"][0]["public_funcs"], 3)
            self.assertEqual(rep["per_script"][0]["test_methods"], 1)


if __name__ == "__main__":
    unittest.main()
