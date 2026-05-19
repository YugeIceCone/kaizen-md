"""Tests for `kaizen handoff diff` — section-by-section delta between 2 yamls.

Per Task #40 brainstorm — item #5. Lets agents (or humans) see exactly
what changed between two handoffs (typically a parent and its child via
the parent_handoff chain) without diffing the full text.

Returns dict[section -> changed_status] where changed_status is one of:
  identical | added | removed | modified
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "scripts/handoff/handoff.py"

sys.path.insert(0, str(_KZ / "scripts/handoff"))
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402


_A = """---
session: test
date: 2026-05-17
status: complete
---

goal: 'do A'
now: 'next thing'
done_this_session:
  - task: 'a'
blockers: []
"""

_B = """---
session: test
date: 2026-05-18
status: complete
---

goal: 'do A'
now: 'a different next'
done_this_session:
  - task: 'a'
  - task: 'b'
blockers: ['something blocking']
findings: ['new finding']
"""


class TestComputeDiff(unittest.TestCase):
    def test_identical_sections(self):
        result = _h._compute_diff(_A, _A)
        for section in result["per_section"].values():
            self.assertEqual(section["status"], "identical")

    def test_modified_section(self):
        result = _h._compute_diff(_A, _B)
        ps = result["per_section"]
        # `now` changed value
        self.assertEqual(ps["now"]["status"], "modified")
        # `done_this_session` grew
        self.assertEqual(ps["done_this_session"]["status"], "modified")
        # `goal` unchanged
        self.assertEqual(ps["goal"]["status"], "identical")

    def test_added_section(self):
        result = _h._compute_diff(_A, _B)
        # findings is in B but absent in A
        self.assertEqual(result["per_section"]["findings"]["status"], "added")

    def test_removed_section(self):
        # B → A: findings disappears
        result = _h._compute_diff(_B, _A)
        self.assertEqual(result["per_section"]["findings"]["status"], "removed")

    def test_summary_counts_correct(self):
        result = _h._compute_diff(_A, _B)
        c = result["counts"]
        # 1 added (findings), 0 removed, 2+ modified (now, done_this_session, possibly blockers)
        self.assertGreaterEqual(c["added"], 1)
        self.assertGreaterEqual(c["modified"], 2)
        self.assertEqual(c["removed"], 0)


class TestDiffCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.a = self.tmp / "a.yaml"
        self.b = self.tmp / "b.yaml"
        self.a.write_text(_A, encoding="utf-8")
        self.b.write_text(_B, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_diff_json(self):
        r = self._run("diff", "--a", str(self.a), "--b", str(self.b), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("per_section", data)
        self.assertIn("counts", data)

    def test_diff_human_output_lists_changes(self):
        r = self._run("diff", "--a", str(self.a), "--b", str(self.b))
        self.assertEqual(r.returncode, 0)
        # Should mention at least one of the changed sections
        self.assertTrue("now" in r.stdout or "done_this_session" in r.stdout
                         or "findings" in r.stdout)

    def test_diff_missing_a_fails(self):
        r = self._run("diff", "--a", str(self.tmp / "nope.yaml"),
                       "--b", str(self.b))
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
