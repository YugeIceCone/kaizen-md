"""complexity (idea #216): radon cc wrapper. Graceful-skip when radon not installed."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import complexity  # noqa: E402


class TestComplexity(unittest.TestCase):
    def test_is_available_is_bool(self):
        self.assertIsInstance(complexity.is_available(), bool)

    def test_scan_unavailable_graceful(self):
        if complexity.is_available():
            self.skipTest("radon installed; can't test fallback")
        rep = complexity.scan(target=_KZ / "scripts/util/brainstorm.py")
        self.assertFalse(rep["available"])
        self.assertEqual(rep["findings"], [])

    def test_scan_when_available(self):
        if not complexity.is_available():
            self.skipTest("radon not installed")
        rep = complexity.scan(target=_KZ / "scripts/util/brainstorm.py")
        self.assertTrue(rep["available"])
        self.assertIsInstance(rep["findings"], list)


if __name__ == "__main__":
    unittest.main()
