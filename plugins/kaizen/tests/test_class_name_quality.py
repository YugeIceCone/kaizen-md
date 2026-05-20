"""class-name-quality (idea #11): class names should be CamelCase + a noun."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import class_name_quality  # noqa: E402

class TestClassNameQuality(unittest.TestCase):
    def test_camel_case_ok(self):
        findings = class_name_quality.scan_text(
            "class MyClass: pass\n", path="ok.py")
        self.assertEqual(findings, [])

    def test_snake_case_flagged(self):
        findings = class_name_quality.scan_text(
            "class my_class: pass\n", path="bad.py")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "not-camelcase")

    def test_lowercase_flagged(self):
        findings = class_name_quality.scan_text(
            "class lowercaseclass: pass\n", path="bad.py")
        self.assertEqual(findings[0]["rule"], "not-camelcase")

if __name__ == "__main__":
    unittest.main()
