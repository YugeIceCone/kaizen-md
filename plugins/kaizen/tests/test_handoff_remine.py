"""Tests for `kaizen handoff re-mine` — refresh + skill-frame capture.

Per Task #40 original-6 items #1 (re-mine) + #5 (skill-frame capture).
Both ride on `mine_session` which already returns both completed_tasks
(re-mine source) AND skills_used (skill-frame source) — KISS to combine.

The subcommand:
  - Reads handoff yaml + finds its cc_session_jsonl link
  - Runs mine_session against that jsonl
  - Identifies completed_tasks not yet in done_this_session ("new")
  - Reports skills_used set
  - With --apply: appends new tasks to done_this_session via the
    existing _append_to_list_section helper
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
_HANDOFF = _KZ / "skills/workflow/scripts/handoff.py"

sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402


def _make_jsonl(path: Path) -> None:
    """Synthesize a CC transcript jsonl with 2 TaskCreate + 2 TaskUpdate."""
    events = []
    # TaskCreate "first" — id=1
    events.append({
        "type": "assistant",
        "uuid": "u1",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu1", "name": "TaskCreate",
             "input": {"subject": "first task"}}
        ]},
    })
    events.append({
        "type": "user",
        "uuid": "r1",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": "Task #1 created successfully: first task"}
        ]},
    })
    # TaskCreate "second" — id=2
    events.append({
        "type": "assistant",
        "uuid": "u2",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu2", "name": "TaskCreate",
             "input": {"subject": "second task"}}
        ]},
    })
    events.append({
        "type": "user",
        "uuid": "r2",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu2",
             "content": "Task #2 created successfully: second task"}
        ]},
    })
    # Skill use
    events.append({
        "type": "assistant",
        "uuid": "u3",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu3", "name": "Skill",
             "input": {"skill": "kaizen:handoff"}}
        ]},
    })
    # TaskUpdate both → completed
    for tid in ("1", "2"):
        events.append({
            "type": "assistant",
            "uuid": f"u_upd_{tid}",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"tu_upd_{tid}", "name": "TaskUpdate",
                 "input": {"taskId": tid, "status": "completed"}}
            ]},
        })
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                     encoding="utf-8")


class TestComputeRemine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.jsonl = self.tmp / "session.jsonl"
        _make_jsonl(self.jsonl)

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_tasks_excludes_already_in_done(self):
        # done_this_session already has "first task" — re-mine should only
        # surface "second task" as new
        existing = ["first task"]
        result = _h._compute_remine(self.jsonl, existing)
        self.assertEqual(result["new_completed_tasks"], ["second task"])
        # skills_used should include kaizen:handoff
        self.assertIn("kaizen:handoff", result["skills_used"])

    def test_no_done_returns_all_completed(self):
        result = _h._compute_remine(self.jsonl, existing=[])
        self.assertEqual(set(result["new_completed_tasks"]),
                          {"first task", "second task"})

    def test_already_complete_returns_empty(self):
        # All tasks already in done → no new
        existing = ["first task", "second task"]
        result = _h._compute_remine(self.jsonl, existing)
        self.assertEqual(result["new_completed_tasks"], [])


class TestRemineCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.jsonl = self.tmp / "session.jsonl"
        _make_jsonl(self.jsonl)
        self.yaml = self.tmp / "h.yaml"
        self.yaml.write_text(
            "---\nsession: test\ndate: 2026-05-18\nstatus: partial\n---\n\n"
            f"session_meta:\n  cc_session_jsonl: '{self.jsonl}'\n\n"
            "goal: 'g'\ndone_this_session:\n  - task: 'first task'\n"
            "    files: []\n",
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_dry_run_reports_new_tasks_without_mutating(self):
        before = self.yaml.read_text()
        r = self._run("re-mine", "--file", str(self.yaml), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["new_completed_tasks"], ["second task"])
        # Yaml unchanged
        self.assertEqual(self.yaml.read_text(), before)

    def test_apply_appends_new_tasks(self):
        r = self._run("re-mine", "--file", str(self.yaml), "--apply", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.yaml.read_text()
        self.assertIn("second task", text)
        # First task NOT duplicated
        self.assertEqual(text.count("first task"), 1)
        self.assertEqual(text.count("second task"), 1)

    def test_missing_jsonl_link_fails_gracefully(self):
        bad = self.tmp / "bad.yaml"
        bad.write_text(
            "---\nsession: test\nstatus: partial\n---\n\ngoal: 'g'\n",
            encoding="utf-8")
        r = self._run("re-mine", "--file", str(bad))
        # Exit non-zero — no session_meta.cc_session_jsonl
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
