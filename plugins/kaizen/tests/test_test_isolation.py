"""test-isolation (idea #22): tests must not touch real ~/.claude/ or
real cwd paths. AST scan flags violations:
  - `Path("~/.claude/...").expanduser()` in test bodies
  - `os.environ["KAIZEN_*"] = ...` without finally-restore
  - Hardcoded `/home/` paths in test bodies
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import test_isolation  # noqa: E402


class TestTestIsolation(unittest.TestCase):
    def test_clean_test_file_no_findings(self):
        src = '''
import unittest, tempfile
class T(unittest.TestCase):
    def test_x(self):
        with tempfile.TemporaryDirectory() as td:
            pass
'''
        findings = test_isolation.scan_text(src, path="clean.py")
        self.assertEqual(findings, [])

    def test_hardcoded_home_flagged(self):
        src = 'p = "/home/cherry86/somefile"\n'
        findings = test_isolation.scan_text(src, path="bad.py")
        self.assertTrue(any(f["rule"] == "hardcoded-home" for f in findings))

    def test_expanduser_claude_flagged(self):
        src = 'from pathlib import Path\np = Path("~/.claude/.kaizen/x").expanduser()\n'
        findings = test_isolation.scan_text(src, path="bad.py")
        self.assertTrue(any(f["rule"] == "expanduser-claude" for f in findings))

    def test_env_mutation_flagged(self):
        src = 'import os\nos.environ["KAIZEN_FOO"] = "bar"\n'
        findings = test_isolation.scan_text(src, path="bad.py")
        self.assertTrue(any(f["rule"] == "env-mutation" for f in findings))

    def test_real_dir_scan_returns_shape(self):
        rep = test_isolation.scan(tests_dir=_KZ / "tests")
        for k in ("tests_total", "findings", "violation_count"):
            self.assertIn(k, rep)


if __name__ == "__main__":
    unittest.main()
