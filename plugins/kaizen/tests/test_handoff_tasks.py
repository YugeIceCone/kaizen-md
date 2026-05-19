"""Tests for `kaizen handoff tasks` — emit TaskCreate-ready JSON per next[] item.

Per Task #40 brainstorm — item #6. After loading a handoff, agents
typically call TaskCreate once per next[] entry. This subcommand emits
the structured payload directly so the agent can skip the parse-then-
mint loop.

Handles both string-form (plain entry) and dict-form
({item, why?, blocker?}) next entries — leveraging the structured-next
work shipped earlier this session.
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


_YAML = """---
session: test
date: 2026-05-18
status: complete
---

goal: 'g'
next:
  - plain string next-action
  - item: structured action with metadata
    why: closes the arc
    blocker: needs user OK
  - another plain string
blockers: []
"""

_EMPTY_NEXT = """---
session: test
date: 2026-05-18
---

goal: 'g'
next: []
"""


class TestExtractTasks(unittest.TestCase):
    def test_extract_handles_both_forms(self):
        result = _h._extract_tasks_from_next(_YAML)
        self.assertEqual(len(result), 3)
        # 1st: plain string
        self.assertEqual(result[0]["subject"], "plain string next-action")
        self.assertNotIn("why", result[0])
        # 2nd: structured
        self.assertEqual(result[1]["subject"], "structured action with metadata")
        self.assertEqual(result[1]["why"], "closes the arc")
        self.assertEqual(result[1]["blocker"], "needs user OK")
        # 3rd: plain string again
        self.assertEqual(result[2]["subject"], "another plain string")

    def test_extract_empty_next_returns_empty(self):
        self.assertEqual(_h._extract_tasks_from_next(_EMPTY_NEXT), [])


class TestTasksCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.yaml = Path(self._tmp.name) / "h.yaml"
        self.yaml.write_text(_YAML, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_tasks_json_emits_list(self):
        r = self._run("tasks", "--file", str(self.yaml), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(len(data["tasks"]), 3)
        self.assertEqual(data["count"], 3)
        # First task has subject only
        self.assertIn("subject", data["tasks"][0])

    def test_tasks_human_lists_subjects(self):
        r = self._run("tasks", "--file", str(self.yaml))
        self.assertEqual(r.returncode, 0)
        for subject in ("plain string next-action",
                         "structured action with metadata",
                         "another plain string"):
            self.assertIn(subject, r.stdout)

    def test_tasks_missing_file_fails(self):
        r = self._run("tasks", "--file", str(Path(self._tmp.name) / "nope.yaml"))
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
