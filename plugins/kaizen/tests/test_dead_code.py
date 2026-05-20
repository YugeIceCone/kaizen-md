"""dead-code (idea #3): vulture wrapper for dead-code detection.
Graceful-skip when vulture is not installed."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import dead_code  # noqa: E402

class TestDeadCode(unittest.TestCase):
    def test_is_available_is_bool(self):
        self.assertIsInstance(dead_code.is_available(), bool)

    def test_scan_when_unavailable_returns_graceful(self):
        if dead_code.is_available():
            self.skipTest("vulture installed; can't test fallback path")
        rep = dead_code.scan(targets=[_KZ / "skills/workflow/scripts"])
        self.assertFalse(rep["available"])
        self.assertEqual(rep["findings"], [])

    def test_scan_when_available_returns_findings_list(self):
        if not dead_code.is_available():
            self.skipTest("vulture not installed")
        rep = dead_code.scan(targets=[_KZ / "skills/workflow/scripts"])
        self.assertTrue(rep["available"])
        self.assertIsInstance(rep["findings"], list)

if __name__ == "__main__":
    unittest.main()
