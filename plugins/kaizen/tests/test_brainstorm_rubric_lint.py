"""T1: brainstorm-rubric.yaml passes `kaizen-rubric lint`.

Catches unknown ops, malformed conditions, signal-name typos at
test-time so the rubric ships green.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_RUBRIC = _KZ / "schemas/brainstorming/brainstorm-rubric.yaml"
_RUBRIC_CLI = _KZ / "scripts/rules/rubric.py"


class TestBrainstormRubricLint(unittest.TestCase):
    def test_rubric_file_exists(self):
        self.assertTrue(_RUBRIC.is_file(), f"missing rubric: {_RUBRIC}")

    def test_kaizen_rubric_lint_passes(self):
        r = subprocess.run(
            [sys.executable, str(_RUBRIC_CLI), "lint",
             "--rubric", str(_RUBRIC)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0,
            f"lint failed:\nstdout: {r.stdout}\nstderr: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
