"""Tests for deus-ex-machina — live session-state mirror.

Fast-store companion to Claude Code's JSONL. The JSONL lags 3–15s
because CC buffers per-turn; dxm captures events sub-millisecond via
hook-driven shell append. CLI queries return real-time state for
scaffold + verify + any consumer that needs "what just happened".

Storage: ~/.claude/.kaizen/dxm/events-<sid>.jsonl  (append-only)
         ~/.claude/.kaizen/dxm/sessions.jsonl       (session lineage)

Env: KAIZEN_DXM_DIR overrides root.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_DXM_PY = _SCRIPTS / "dxm.py"


class DxmBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_DXM_DIR", None)
        else: os.environ["KAIZEN_DXM_DIR"] = self._orig

    def _run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DXM_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


# ─── capture ─────────────────────────────────────────────────────────


class TestCapture(DxmBase):
    def test_capture_appends_event_to_session_jsonl(self):
        payload = json.dumps({
            "session_id": "sess1",
            "evt_type": "tool.invoke",
            "tool_name": "Bash",
            "payload": {"command": "ls"},
        })
        r = self._run("capture", "--json", stdin=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        jsonl = self.tmp / "events-sess1.jsonl"
        self.assertTrue(jsonl.is_file())
        lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["evt_type"], "tool.invoke")
        self.assertEqual(rec["tool_name"], "Bash")
        self.assertIn("ts_unix", rec)
        self.assertIsInstance(rec["ts_unix"], (int, float))

    def test_capture_multiple_events_appends_in_order(self):
        for i, evt in enumerate(["a", "b", "c"]):
            self._run("capture", stdin=json.dumps({
                "session_id": "s2",
                "evt_type": evt,
            }))
            time.sleep(0.005)  # ensure distinct ts_unix
        jsonl = self.tmp / "events-s2.jsonl"
        lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual([json.loads(l)["evt_type"] for l in lines],
                          ["a", "b", "c"])

    def test_capture_missing_session_id_errors(self):
        r = self._run("capture", stdin=json.dumps({"evt_type": "x"}))
        self.assertNotEqual(r.returncode, 0)

    def test_capture_missing_evt_type_errors(self):
        r = self._run("capture", stdin=json.dumps({"session_id": "s"}))
        self.assertNotEqual(r.returncode, 0)

    def test_capture_malformed_json_errors(self):
        r = self._run("capture", stdin="not-json")
        self.assertNotEqual(r.returncode, 0)

    def test_capture_no_op_when_disabled(self):
        os.environ["KAIZEN_DXM_DISABLE"] = "1"
        try:
            r = self._run("capture", stdin=json.dumps({
                "session_id": "s3", "evt_type": "x"}))
            self.assertEqual(r.returncode, 0)
            self.assertFalse((self.tmp / "events-s3.jsonl").exists())
        finally:
            del os.environ["KAIZEN_DXM_DISABLE"]


# ─── now (current session-state snapshot) ────────────────────────────


class TestNow(DxmBase):
    def _seed(self, session_id: str, events: list[dict]):
        for e in events:
            self._run("capture", stdin=json.dumps({
                "session_id": session_id, **e}))
            time.sleep(0.005)

    def test_now_returns_event_count_per_session(self):
        self._seed("s1", [
            {"evt_type": "tool.invoke", "tool_name": "Bash"},
            {"evt_type": "tool.invoke", "tool_name": "Edit"},
            {"evt_type": "tool.complete", "tool_name": "Bash"},
        ])
        r = self._run("now", "--session", "s1", "--json")
        env = json.loads(r.stdout)
        d = env["data"]
        self.assertEqual(d["session_id"], "s1")
        self.assertEqual(d["event_count"], 3)
        self.assertIn("Bash", d["by_tool"])
        self.assertEqual(d["by_tool"]["Bash"], 2)
        self.assertEqual(d["by_tool"]["Edit"], 1)

    def test_now_returns_last_event_at(self):
        self._seed("s2", [
            {"evt_type": "x"}, {"evt_type": "y"}, {"evt_type": "z"},
        ])
        r = self._run("now", "--session", "s2", "--json")
        env = json.loads(r.stdout)
        self.assertIn("last_event_at_unix", env["data"])
        self.assertGreater(env["data"]["last_event_at_unix"], 0)

    def test_now_lag_field_is_seconds_since_last_event(self):
        self._seed("s3", [{"evt_type": "x"}])
        time.sleep(0.1)
        r = self._run("now", "--session", "s3", "--json")
        env = json.loads(r.stdout)
        self.assertGreater(env["data"]["lag_seconds"], 0.05)

    def test_now_for_unknown_session_returns_empty(self):
        r = self._run("now", "--session", "never", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["event_count"], 0)
        self.assertEqual(env["data"]["by_tool"], {})


# ─── tail ────────────────────────────────────────────────────────────


class TestTail(DxmBase):
    def _seed(self, session_id: str, n: int):
        for i in range(n):
            self._run("capture", stdin=json.dumps({
                "session_id": session_id, "evt_type": f"e{i}"}))
            time.sleep(0.003)

    def test_tail_returns_last_n_events(self):
        self._seed("s", 10)
        r = self._run("tail", "--session", "s", "--limit", "3", "--json")
        env = json.loads(r.stdout)
        events = env["data"]["events"]
        self.assertEqual(len(events), 3)
        self.assertEqual([e["evt_type"] for e in events], ["e7", "e8", "e9"])

    def test_tail_since_unix_filters(self):
        self._seed("s2", 5)
        # Capture cutoff between event 2 and 3
        import time as t
        cutoff = t.time()
        t.sleep(0.05)
        self._run("capture", stdin=json.dumps({
            "session_id": "s2", "evt_type": "after"}))
        r = self._run("tail", "--session", "s2",
                       "--since-unix", str(cutoff), "--json")
        env = json.loads(r.stdout)
        events = env["data"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["evt_type"], "after")


# ─── link (cross-session continuity) ─────────────────────────────────


class TestLink(DxmBase):
    def test_link_records_parent_child(self):
        r = self._run("link", "--parent", "sess-prev", "--child", "sess-curr", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        sessions = self.tmp / "sessions.jsonl"
        self.assertTrue(sessions.is_file())
        rec = json.loads(sessions.read_text().strip().splitlines()[-1])
        self.assertEqual(rec["parent_session_id"], "sess-prev")
        self.assertEqual(rec["child_session_id"], "sess-curr")

    def test_now_includes_parent_when_linked(self):
        self._run("link", "--parent", "P", "--child", "C")
        r = self._run("now", "--session", "C", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"].get("parent_session_id"), "P")


class TestHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run([sys.executable, str(_DXM_PY), "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
