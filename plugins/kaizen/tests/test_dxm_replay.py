"""Tests for `kaizen-dxm replay` — backfill from CC's session JSONL.

Fixes the install-day blindspot: when dxm is installed mid-session,
CC won't re-register the hook until session reload. `replay` walks
the JSONL CC already wrote and synthesizes the equivalent dxm
events into events-<sid>.jsonl, so consumers (scaffold, verify,
now-snapshot) see the full session history immediately.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_DXM_PY = _KZ_DIR / "scripts" / "observe" / "dxm.py"


def _make_jsonl(records: list[dict]) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


# Mirrors the shape of CC's persisted JSONL attachments — hook events
# land as `type: "attachment"` with `attachment.hookEvent` discriminator.
_REPLAY_FIXTURE = [
    {"type": "user", "timestamp": "2026-05-17T05:00:00.000Z",
      "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}},
    {"type": "attachment", "timestamp": "2026-05-17T05:00:01.000Z",
      "sessionId": "replay-sess",
      "attachment": {"type": "hook_success", "hookName": "PreToolUse:Bash",
                     "hookEvent": "PreToolUse",
                     "toolUseID": "toolu_aaa", "command": "ls", "exitCode": 0}},
    {"type": "attachment", "timestamp": "2026-05-17T05:00:01.100Z",
      "sessionId": "replay-sess",
      "attachment": {"type": "hook_success", "hookName": "PostToolUse:Bash",
                     "hookEvent": "PostToolUse",
                     "toolUseID": "toolu_aaa", "durationMs": 12, "exitCode": 0}},
    # Lines that should be SKIPPED:
    {"type": "ai-title", "aiTitle": "test session"},
    {"type": "file-history-snapshot", "snapshot": {}},
    # Another tool round
    {"type": "attachment", "timestamp": "2026-05-17T05:00:02.000Z",
      "sessionId": "replay-sess",
      "attachment": {"type": "hook_success", "hookName": "PreToolUse:Edit",
                     "hookEvent": "PreToolUse",
                     "toolUseID": "toolu_bbb"}},
    {"type": "attachment", "timestamp": "2026-05-17T05:00:02.050Z",
      "sessionId": "replay-sess",
      "attachment": {"type": "hook_success", "hookName": "PostToolUse:Edit",
                     "hookEvent": "PostToolUse",
                     "toolUseID": "toolu_bbb", "durationMs": 8}},
    # Lifecycle event mid-session
    {"type": "attachment", "timestamp": "2026-05-17T05:00:03.000Z",
      "sessionId": "replay-sess",
      "attachment": {"type": "hook_success",
                     "hookEvent": "UserPromptSubmit",
                     "hookName": "UserPromptSubmit"}},
]


class ReplayBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Sandbox the JSONL source location + dxm output dir
        self.jsonl_dir = self.tmp / "projects"
        self.jsonl_dir.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self._orig_dxm = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.dxm_dir)
        self._jsonl_path = self.jsonl_dir / "replay-sess.jsonl"
        self._jsonl_path.write_text(_make_jsonl(_REPLAY_FIXTURE),
                                      encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig_dxm is None: os.environ.pop("KAIZEN_DXM_DIR", None)
        else: os.environ["KAIZEN_DXM_DIR"] = self._orig_dxm

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DXM_PY), *args],
            capture_output=True, text=True, timeout=15, env=os.environ.copy(),
        )

    def _read_events(self, sid: str) -> list[dict]:
        p = self.dxm_dir / f"events-{sid}.jsonl"
        if not p.is_file(): return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


class TestReplayBasic(ReplayBase):
    def test_creates_events_file(self):
        r = self._run("replay",
                       "--session", "replay-sess",
                       "--jsonl", str(self._jsonl_path), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events("replay-sess")
        # 5 hook events in fixture (2 Pre/Post pairs + 1 UserPromptSubmit)
        self.assertEqual(len(events), 5)

    def test_skips_non_hook_lines(self):
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path), "--json")
        events = self._read_events("replay-sess")
        # No file-history-snapshot or ai-title events
        evt_types = [e["evt_type"] for e in events]
        self.assertNotIn("file-history-snapshot", evt_types)
        self.assertNotIn("ai-title", evt_types)

    def test_preserves_event_order(self):
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path), "--json")
        events = self._read_events("replay-sess")
        self.assertEqual(
            [e["evt_type"] for e in events],
            ["PreToolUse", "PostToolUse", "PreToolUse", "PostToolUse",
              "UserPromptSubmit"],
        )

    def test_extracts_tool_use_id_from_attachment(self):
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path), "--json")
        events = self._read_events("replay-sess")
        pre_events = [e for e in events if e["evt_type"] == "PreToolUse"]
        self.assertEqual(pre_events[0].get("tool_use_id"), "toolu_aaa")
        self.assertEqual(pre_events[1].get("tool_use_id"), "toolu_bbb")

    def test_extracts_duration_ms_from_post(self):
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path), "--json")
        events = self._read_events("replay-sess")
        post = [e for e in events if e["evt_type"] == "PostToolUse"]
        self.assertEqual(post[0].get("duration_ms"), 12)
        self.assertEqual(post[1].get("duration_ms"), 8)

    def test_extracts_tool_name_from_hookName(self):
        """attachment.hookName format is 'PreToolUse:Bash' — tool name
        is after the colon."""
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path), "--json")
        events = self._read_events("replay-sess")
        pre = [e for e in events if e["evt_type"] == "PreToolUse"]
        self.assertEqual(pre[0].get("tool_name"), "Bash")
        self.assertEqual(pre[1].get("tool_name"), "Edit")


class TestReplayTruncate(ReplayBase):
    def test_default_truncates_existing(self):
        # Pre-seed an existing events file with stale data
        self.dxm_dir.mkdir(parents=True, exist_ok=True)
        stale = self.dxm_dir / "events-replay-sess.jsonl"
        stale.write_text(json.dumps({
            "ts_unix": 100.0, "session_id": "replay-sess",
            "evt_type": "OLD"}) + "\n")
        # Replay (default truncates)
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path), "--json")
        events = self._read_events("replay-sess")
        evt_types = [e["evt_type"] for e in events]
        self.assertNotIn("OLD", evt_types)

    def test_no_truncate_appends(self):
        self.dxm_dir.mkdir(parents=True, exist_ok=True)
        existing = self.dxm_dir / "events-replay-sess.jsonl"
        existing.write_text(json.dumps({
            "ts_unix": 100.0, "session_id": "replay-sess",
            "evt_type": "PRE_EXISTING"}) + "\n")
        self._run("replay", "--session", "replay-sess",
                   "--jsonl", str(self._jsonl_path),
                   "--no-truncate", "--json")
        events = self._read_events("replay-sess")
        evt_types = [e["evt_type"] for e in events]
        self.assertIn("PRE_EXISTING", evt_types)
        # Plus the 5 replayed events
        self.assertEqual(len(events), 6)


class TestReplayMissingFile(ReplayBase):
    def test_missing_jsonl_errors(self):
        r = self._run("replay", "--session", "replay-sess",
                       "--jsonl", str(self.tmp / "nope.jsonl"),
                       "--json")
        self.assertNotEqual(r.returncode, 0)


class TestReplayEnvelope(ReplayBase):
    def test_returns_synthesized_count(self):
        r = self._run("replay", "--session", "replay-sess",
                       "--jsonl", str(self._jsonl_path), "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["synthesized_count"], 5)
        self.assertEqual(env["data"]["session_id"], "replay-sess")


class TestReplayHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run([sys.executable, str(_DXM_PY), "replay", "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
