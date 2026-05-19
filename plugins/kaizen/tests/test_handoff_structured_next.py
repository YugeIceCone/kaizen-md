"""Tests for structured next[] — append with --why / --blocker flags.

Per Task #40 original-6 item #2 (structured next[]). Promotes plain
string entries in `next:` to `{item, why?, blocker?}` dicts when the
caller supplies the metadata. Back-compat: plain --entry stays string.

Reuses _format_entry_yaml's existing dict-handling — only the CLI
plumbing changes (new flags, dict-build logic in _cmd_append).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "scripts/handoff/handoff.py"


_YAML = """---
session: test
date: 2026-05-18
status: partial
---

next: []
blockers: []
"""


class TestStructuredNextAppend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.yaml = Path(self._tmp.name) / "h.yaml"
        self.yaml.write_text(_YAML, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_plain_entry_stays_string(self):
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "next", "--entry", "ship the thing")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        # Plain string form
        self.assertIn("ship the thing", text)
        # NOT in dict form
        self.assertNotIn("item: ship the thing", text)

    def test_why_promotes_to_dict(self):
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "next", "--entry", "rerun gate",
                       "--why", "previous run hit a flaky test")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("item: rerun gate", text)
        self.assertIn("flaky test", text)

    def test_blocker_promotes_to_dict(self):
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "next", "--entry", "push to remote",
                       "--blocker", "need user OK for force-push")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("item: push to remote", text)
        self.assertIn("blocker: need user OK", text)

    def test_why_and_blocker_full_dict(self):
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "next", "--entry", "deploy",
                       "--why", "ship the feature",
                       "--blocker", "CI failing")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        self.assertIn("item: deploy", text)
        self.assertIn("why: ship the feature", text)
        self.assertIn("blocker: CI failing", text)

    def test_why_ignored_on_done_section(self):
        # done_this_session has its own dict shape (task/files); --why
        # is a no-op there for KISS — only `next` gets the promotion.
        r = self._run("append", "--file", str(self.yaml),
                       "--section", "done_this_session",
                       "--task", "did a thing",
                       "--why", "should be ignored")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text(encoding="utf-8")
        # done entry still has task — no "why" field
        self.assertIn("task: did a thing", text)
        self.assertNotIn("why: should be ignored", text)


if __name__ == "__main__":
    unittest.main()
