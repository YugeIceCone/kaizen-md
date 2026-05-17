"""Tests for _session_jsonl.py — Claude Code session JSONL miner.

Closes the "agent re-derives session state from memory" inefficiency by
extracting what the harness already records: latest ai_title (goal
candidate), TaskCreate/TaskUpdate flow (done + next candidates),
file touches, skills used, session start timestamp.

Used by handoff scaffold to slash ~80% of the agent's compose-from-
memory cost.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))


def _make_jsonl(*records: dict) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


_SAMPLE_RECORDS = [
    {"type": "file-history-snapshot", "messageId": "m1",
      "snapshot": {"messageId": "m1", "trackedFileBackups": {},
                    "timestamp": "2026-05-17T03:00:00.000Z"}},
    {"type": "user", "uuid": "u1", "timestamp": "2026-05-17T03:00:01.000Z",
      "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}},
    {"type": "ai-title", "aiTitle": "Initial title (revised later)",
      "sessionId": "s1"},
    {"type": "assistant", "uuid": "a1", "timestamp": "2026-05-17T03:00:05.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_1", "name": "TaskCreate",
            "input": {"subject": "Build verify subcommand", "description": "..."}}]}},
    {"type": "user", "uuid": "u2", "timestamp": "2026-05-17T03:00:06.000Z",
      "message": {"role": "user", "content": [
          {"type": "tool_result", "tool_use_id": "tu_1",
            "content": "Task #1 created successfully: Build verify subcommand"}]}},
    {"type": "assistant", "uuid": "a2", "timestamp": "2026-05-17T03:00:10.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_2", "name": "TaskCreate",
            "input": {"subject": "Add scaffold", "description": "..."}}]}},
    {"type": "user", "uuid": "u3", "timestamp": "2026-05-17T03:00:11.000Z",
      "message": {"role": "user", "content": [
          {"type": "tool_result", "tool_use_id": "tu_2",
            "content": "Task #2 created successfully: Add scaffold"}]}},
    # Mark task 1 in progress, then completed
    {"type": "assistant", "uuid": "a3", "timestamp": "2026-05-17T03:00:20.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_3", "name": "TaskUpdate",
            "input": {"taskId": "1", "status": "in_progress"}}]}},
    {"type": "assistant", "uuid": "a4", "timestamp": "2026-05-17T03:00:30.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_4", "name": "TaskUpdate",
            "input": {"taskId": "1", "status": "completed"}}]}},
    # File touches: Edit + Read
    {"type": "assistant", "uuid": "a5", "timestamp": "2026-05-17T03:00:40.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_5", "name": "Edit",
            "input": {"file_path": "src/foo.py", "old_string": "x", "new_string": "y"}}]}},
    {"type": "assistant", "uuid": "a6", "timestamp": "2026-05-17T03:00:50.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_6", "name": "Read",
            "input": {"file_path": "src/bar.py"}}]}},
    {"type": "assistant", "uuid": "a7", "timestamp": "2026-05-17T03:01:00.000Z",
      "message": {"role": "assistant", "content": [
          {"type": "tool_use", "id": "tu_7", "name": "Skill",
            "input": {"skill": "kaizen:handoff", "args": ""}}]}},
    # Final ai-title (the one to use)
    {"type": "ai-title",
      "aiTitle": "Streamline handoff with session JSONL mining",
      "sessionId": "s1"},
]


class TestDiscoverSessionJsonl(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_returns_latest_jsonl_by_mtime(self):
        import _session_jsonl as sj
        # Two jsonl files; second is newer
        (self.tmp / "first.jsonl").write_text("{}\n")
        import time; time.sleep(0.01)
        (self.tmp / "second.jsonl").write_text("{}\n")
        result = sj.discover_session_jsonl(self.tmp)
        self.assertEqual(result.name, "second.jsonl")

    def test_returns_none_when_no_jsonl(self):
        import _session_jsonl as sj
        self.assertIsNone(sj.discover_session_jsonl(self.tmp))

    def test_returns_none_when_dir_missing(self):
        import _session_jsonl as sj
        self.assertIsNone(sj.discover_session_jsonl(self.tmp / "does-not-exist"))

    def test_ignores_subdirs(self):
        import _session_jsonl as sj
        (self.tmp / "sub").mkdir()
        (self.tmp / "sub" / "nested.jsonl").write_text("{}\n")
        # Only top-level *.jsonl considered
        self.assertIsNone(sj.discover_session_jsonl(self.tmp))


class TestCwdToProjectSlug(unittest.TestCase):
    def test_absolute_path_slug(self):
        import _session_jsonl as sj
        slug = sj.cwd_to_slug(Path("/home/user/workspace/kaizen-md"))
        self.assertEqual(slug, "-home-user-workspace-kaizen-md")

    def test_root_slash(self):
        import _session_jsonl as sj
        slug = sj.cwd_to_slug(Path("/"))
        # Just "/" → "-" or empty leading is fine; matches CC behavior
        self.assertTrue(slug.startswith("-"))


class TestMineSession(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.jsonl = self.tmp / "s.jsonl"
        self.jsonl.write_text(_make_jsonl(*_SAMPLE_RECORDS), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_extracts_latest_ai_title(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        self.assertEqual(mined["ai_title"],
                          "Streamline handoff with session JSONL mining")

    def test_extracts_session_started_at(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        # First timestamped record
        self.assertEqual(mined["session_started_at"],
                          "2026-05-17T03:00:00.000Z")

    def test_tasks_map_links_create_to_subject_and_status(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        tasks = mined["tasks"]
        # Task 1: created + completed
        self.assertIn("1", tasks)
        self.assertEqual(tasks["1"]["subject"], "Build verify subcommand")
        self.assertEqual(tasks["1"]["status"], "completed")
        # Task 2: created only, no update → status defaults to pending
        self.assertIn("2", tasks)
        self.assertEqual(tasks["2"]["subject"], "Add scaffold")
        self.assertEqual(tasks["2"]["status"], "pending")

    def test_completed_tasks_list(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        self.assertEqual(mined["completed_tasks"], ["Build verify subcommand"])

    def test_pending_tasks_list(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        self.assertEqual(mined["pending_tasks"], ["Add scaffold"])

    def test_files_touched_collects_edit_and_read(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        self.assertEqual(
            sorted(mined["files_touched"]),
            ["src/bar.py", "src/foo.py"],
        )

    def test_skills_used_collects_skill_invocations(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        self.assertIn("kaizen:handoff", mined["skills_used"])

    def test_tools_used_counts(self):
        import _session_jsonl as sj
        mined = sj.mine_session(self.jsonl)
        # Sample fixture: 2 TaskCreate, 2 TaskUpdate, 1 Edit, 1 Read, 1 Skill
        counts = mined["tools_used_counts"]
        self.assertEqual(counts.get("TaskCreate"), 2)
        self.assertEqual(counts.get("TaskUpdate"), 2)
        self.assertEqual(counts.get("Edit"), 1)
        self.assertEqual(counts.get("Read"), 1)
        self.assertEqual(counts.get("Skill"), 1)

    def test_robust_to_missing_or_malformed_lines(self):
        import _session_jsonl as sj
        # Include a malformed line + one without timestamp
        bad = self.jsonl.read_text() + "not-json\n" + json.dumps({"type": "no-ts"}) + "\n"
        self.jsonl.write_text(bad, encoding="utf-8")
        mined = sj.mine_session(self.jsonl)
        # Still returns valid structure
        self.assertIn("ai_title", mined)
        self.assertIsNotNone(mined["ai_title"])


class TestMineSessionEmpty(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_jsonl_returns_empty_structure(self):
        import _session_jsonl as sj
        p = self.tmp / "empty.jsonl"
        p.write_text("")
        mined = sj.mine_session(p)
        self.assertIsNone(mined["ai_title"])
        self.assertEqual(mined["tasks"], {})
        self.assertEqual(mined["completed_tasks"], [])
        self.assertEqual(mined["pending_tasks"], [])


if __name__ == "__main__":
    unittest.main()
