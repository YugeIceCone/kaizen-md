"""Tests for dxm-event.sh — the sub-millisecond capture hook.

Feeds canned event JSON to the hook via stdin and asserts the
resulting JSONL line shape in events-<sid>.jsonl. Pure-shell hot
path coverage that catches regressions in the grep/sed/printf
extractors.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/dxm-event.sh"


class DxmHookBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_DXM_DIR", None)
        else: os.environ["KAIZEN_DXM_DIR"] = self._orig

    def _fire(self, evt_name: str, event_json: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(_HOOK), evt_name],
            input=json.dumps(event_json), capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )

    def _read_events(self, sid: str) -> list[dict]:
        path = self.tmp / f"events-{sid}.jsonl"
        if not path.is_file():
            return []
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ─── Per-event-type capture ──────────────────────────────────────────


class TestPreToolUseCapture(DxmHookBase):
    def test_captures_session_id_and_tool_name(self):
        r = self._fire("PreToolUse", {
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        })
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events("s1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["session_id"], "s1")
        self.assertEqual(events[0]["evt_type"], "PreToolUse")
        self.assertEqual(events[0]["tool_name"], "Bash")
        self.assertIn("ts_unix", events[0])
        self.assertIsInstance(events[0]["ts_unix"], (int, float))

    def test_captures_tool_use_id(self):
        r = self._fire("PreToolUse", {
            "session_id": "s2", "tool_name": "Edit",
            "tool_use_id": "toolu_01ABCdefGHI",
        })
        events = self._read_events("s2")
        self.assertEqual(events[0].get("tool_use_id"), "toolu_01ABCdefGHI")


class TestPostToolUseCapture(DxmHookBase):
    def test_captures_duration_and_exit_code(self):
        # CC's PostToolUse carries duration_ms and exit_code in
        # tool_response (camelCase in the attachment, but we feed
        # via stdin in snake_case as the hook reads from the event payload).
        r = self._fire("PostToolUse", {
            "session_id": "s3", "tool_name": "Bash",
            "tool_use_id": "toolu_xyz",
            "duration_ms": 156,
            "exit_code": 0,
        })
        events = self._read_events("s3")
        self.assertEqual(events[0]["evt_type"], "PostToolUse")
        self.assertEqual(events[0].get("duration_ms"), 156)
        self.assertEqual(events[0].get("exit_code"), 0)

    def test_post_without_duration_still_captures(self):
        r = self._fire("PostToolUse", {
            "session_id": "s4", "tool_name": "Read",
        })
        self.assertEqual(r.returncode, 0, r.stderr)
        events = self._read_events("s4")
        self.assertEqual(len(events), 1)


class TestUserPromptSubmitCapture(DxmHookBase):
    def test_captures_without_tool_name(self):
        r = self._fire("UserPromptSubmit", {"session_id": "s5"})
        events = self._read_events("s5")
        self.assertEqual(events[0]["evt_type"], "UserPromptSubmit")
        # tool_name absent → field not present (or null)
        self.assertNotIn("tool_name", events[0])


class TestSessionStartCapture(DxmHookBase):
    def test_records_session_boundary(self):
        r = self._fire("SessionStart", {"session_id": "s6"})
        events = self._read_events("s6")
        self.assertEqual(events[0]["evt_type"], "SessionStart")


class TestSessionEndCapture(DxmHookBase):
    def test_records_session_end(self):
        r = self._fire("SessionEnd", {"session_id": "s7"})
        events = self._read_events("s7")
        self.assertEqual(events[0]["evt_type"], "SessionEnd")


class TestStopCapture(DxmHookBase):
    def test_captures_turn_boundary(self):
        r = self._fire("Stop", {"session_id": "s8"})
        events = self._read_events("s8")
        self.assertEqual(events[0]["evt_type"], "Stop")


class TestSubagentStopCapture(DxmHookBase):
    def test_captures_subagent_completion(self):
        r = self._fire("SubagentStop", {"session_id": "s9"})
        events = self._read_events("s9")
        self.assertEqual(events[0]["evt_type"], "SubagentStop")


class TestPreCompactCapture(DxmHookBase):
    def test_captures_compaction_boundary(self):
        r = self._fire("PreCompact", {"session_id": "s10"})
        events = self._read_events("s10")
        self.assertEqual(events[0]["evt_type"], "PreCompact")


class TestNotificationCapture(DxmHookBase):
    def test_captures_notification(self):
        r = self._fire("Notification", {"session_id": "s11"})
        events = self._read_events("s11")
        self.assertEqual(events[0]["evt_type"], "Notification")


# ─── Hook discipline (bypass + degenerate cases) ─────────────────────


class TestDisableBypass(DxmHookBase):
    def test_no_op_when_disable_env_set(self):
        os.environ["KAIZEN_DXM_DISABLE"] = "1"
        try:
            r = self._fire("PreToolUse", {
                "session_id": "s12", "tool_name": "Bash"})
            self.assertEqual(r.returncode, 0)
            # No JSONL written
            self.assertFalse((self.tmp / "events-s12.jsonl").exists())
        finally:
            del os.environ["KAIZEN_DXM_DISABLE"]


class TestNoOpWhenSessionIdMissing(DxmHookBase):
    def test_event_without_session_id_silently_skipped(self):
        r = self._fire("PreToolUse", {"tool_name": "Bash"})
        # Hook always exits 0 and prints {} (never blocks host flow)
        self.assertEqual(r.returncode, 0)
        # No file created
        files = list(self.tmp.glob("events-*.jsonl"))
        self.assertEqual(files, [])


class TestMalformedJsonGracefulNoOp(DxmHookBase):
    def test_malformed_stdin_does_not_crash(self):
        r = subprocess.run(
            ["bash", str(_HOOK), "PreToolUse"],
            input="not-json", capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        # Hook never blocks host flow — always exit 0
        self.assertEqual(r.returncode, 0)


class TestHookEmitsEmptyJsonOnStdout(DxmHookBase):
    def test_stdout_is_empty_json(self):
        """Hook contract: print {} so the host hook chain doesn't break."""
        r = self._fire("PreToolUse", {"session_id": "s13"})
        self.assertEqual(r.stdout.strip(), "{}")


# ─── JSON-line shape integrity ───────────────────────────────────────


class TestJsonlLineIsValidJson(DxmHookBase):
    """Every line the hook writes must be parseable JSON. Catches
    quoting bugs in the printf template."""

    def test_line_round_trips_through_json_load(self):
        r = self._fire("PreToolUse", {
            "session_id": "s14", "tool_name": "Bash",
        })
        raw = (self.tmp / "events-s14.jsonl").read_text().strip()
        # Must parse without raising
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)

    def test_special_chars_in_tool_name_handled(self):
        # CC's tool_name shouldn't have quotes, but defensive:
        # mcp__server__tool patterns have underscores which are safe.
        r = self._fire("PreToolUse", {
            "session_id": "s15",
            "tool_name": "mcp__server__tool_call",
        })
        events = self._read_events("s15")
        self.assertEqual(events[0]["tool_name"], "mcp__server__tool_call")


if __name__ == "__main__":
    unittest.main()
