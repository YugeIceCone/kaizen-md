"""Tests for kaizen-frontmatter — SKILL.md frontmatter audit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/frontmatter.py"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10, env=os.environ.copy(),
    )


class TestScriptHealth(unittest.TestCase):
    def test_script_parses(self):
        with open(_SCRIPT) as f:
            compile(f.read(), str(_SCRIPT), "exec")


class TestAuditSkill(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "frontmatter" in sys.modules:
            del sys.modules["frontmatter"]
        import frontmatter as fm
        self.fm = fm
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _skill(self, name: str, body: str) -> Path:
        d = self.root / name
        d.mkdir()
        (d / "SKILL.md").write_text(body)
        return d

    def test_conformant_skill_passes(self):
        d = self._skill("foo", '---\nname: foo\ndescription: '
            'Do X when "trigger one" or "trigger two" or "trigger three".\n---\nbody\n')
        r = self.fm.audit_skill(d)
        self.assertTrue(r["conformant"])
        self.assertTrue(r["name_match"])
        self.assertGreaterEqual(r["trigger_count"], 3)
        self.assertEqual(r["gaps"], [])

    def test_name_mismatch_flagged(self):
        d = self._skill("foo", '---\nname: bar\ndescription: '
            '"a" "b" "c"\n---\nbody\n')
        r = self.fm.audit_skill(d)
        self.assertFalse(r["name_match"])
        self.assertFalse(r["conformant"])
        self.assertTrue(any("name-mismatch" in g for g in r["gaps"]))

    def test_weak_routing_flagged(self):
        d = self._skill("foo", '---\nname: foo\ndescription: '
            'Just one quote: "only one".\n---\nbody\n')
        r = self.fm.audit_skill(d)
        self.assertFalse(r["conformant"])
        self.assertEqual(r["trigger_count"], 1)
        self.assertTrue(any("weak-routing" in g for g in r["gaps"]))

    def test_no_frontmatter_flagged(self):
        d = self._skill("foo", "# just a markdown file\nno frontmatter\n")
        r = self.fm.audit_skill(d)
        self.assertIn("no-frontmatter", r["gaps"])

    def test_no_name_field_flagged(self):
        d = self._skill("foo", '---\ndescription: "a" "b" "c"\n---\nbody\n')
        r = self.fm.audit_skill(d)
        self.assertIn("no-name-field", r["gaps"])

    def test_quoted_phrases_counted_single_or_double(self):
        d = self._skill("foo", "---\nname: foo\ndescription: "
            '"double" \'single\' "more".\n---\nbody\n')
        r = self.fm.audit_skill(d)
        self.assertEqual(r["trigger_count"], 3)


class TestRealPluginReport(unittest.TestCase):
    def test_report_runs(self):
        r = _run("report")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("frontmatter:", r.stdout)

    def test_report_json_shape(self):
        r = _run("report", "--json")
        data = json.loads(r.stdout)
        self.assertGreater(len(data), 50)
        for entry in data[:3]:
            for k in ("skill", "path", "name_field", "name_match",
                       "trigger_count", "gaps", "conformant"):
                self.assertIn(k, entry)

    def test_gaps_exit_codes(self):
        """Real plugin has known frontmatter gaps → exit 1."""
        r = _run("gaps")
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
