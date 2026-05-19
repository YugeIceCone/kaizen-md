"""subprocess-rc (idea #32): AST scan for subprocess.run calls without rc check."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import subprocess_rc  # noqa: E402


class TestSubprocessRc(unittest.TestCase):
    def test_ignored_return_flagged(self):
        src = "import subprocess\nsubprocess.run(['ls'])\n"
        findings = subprocess_rc.scan_text(src, path="bad.py")
        self.assertEqual(len(findings), 1)

    def test_assigned_to_var_ok(self):
        src = "import subprocess\nr = subprocess.run(['ls'])\nprint(r.returncode)\n"
        findings = subprocess_rc.scan_text(src, path="ok.py")
        self.assertEqual(findings, [])

    def test_check_true_kwarg_ok(self):
        src = "import subprocess\nsubprocess.run(['ls'], check=True)\n"
        findings = subprocess_rc.scan_text(src, path="ok.py")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
