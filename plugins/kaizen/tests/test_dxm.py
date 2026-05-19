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
_DXM_PY = _KZ_DIR / "scripts" / "observe" / "dxm.py"


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


class TestTailRollingWindow(DxmBase):
    """`tail --back N` returns events from (now - N) to now.
    `--window-from F --window-to T` returns events from (now - F) to (now - T)."""

    def _seed(self, session_id: str, n: int, gap: float = 0.05):
        for i in range(n):
            self._run("capture", stdin=json.dumps({
                "session_id": session_id, "evt_type": f"e{i}"}))
            time.sleep(gap)

    def test_back_seconds_filters_to_recent_window(self):
        self._seed("rw", 3, gap=0.1)   # ~300ms total
        time.sleep(0.4)                # all events now >300ms old
        # Add a fresh event INSIDE the 200ms window
        self._run("capture", stdin=json.dumps({
            "session_id": "rw", "evt_type": "fresh"}))
        r = self._run("tail", "--session", "rw", "--back", "0.2", "--json")
        env = json.loads(r.stdout)
        events = env["data"]["events"]
        # Only `fresh` survives the 200ms window
        self.assertEqual([e["evt_type"] for e in events], ["fresh"])

    def test_back_combines_with_limit(self):
        self._seed("rw2", 5, gap=0.01)
        # Wide window catches all 5; limit narrows to last 2
        r = self._run("tail", "--session", "rw2",
                       "--back", "10", "--limit", "2", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(len(env["data"]["events"]), 2)
        self.assertEqual(
            [e["evt_type"] for e in env["data"]["events"]],
            ["e3", "e4"],
        )

    def test_window_from_to_returns_middle_slice(self):
        # Seed events with measurable gaps:
        # - 1 event at t=0
        # - sleep 0.3
        # - 1 event at t=0.3
        # - sleep 0.3
        # - 1 event at t=0.6
        self._run("capture", stdin=json.dumps({
            "session_id": "wf", "evt_type": "old"}))
        time.sleep(0.3)
        self._run("capture", stdin=json.dumps({
            "session_id": "wf", "evt_type": "middle"}))
        time.sleep(0.3)
        self._run("capture", stdin=json.dumps({
            "session_id": "wf", "evt_type": "recent"}))

        # Window: from=0.5s ago, to=0.15s ago → captures `middle` only
        r = self._run("tail", "--session", "wf",
                       "--window-from", "0.5",
                       "--window-to", "0.15", "--json")
        env = json.loads(r.stdout)
        evts = [e["evt_type"] for e in env["data"]["events"]]
        # Allow ±1 entry tolerance for timing jitter — at minimum `middle`
        # is in the window
        self.assertIn("middle", evts)

    def test_negative_back_rejected(self):
        r = self._run("tail", "--session", "rw3", "--back", "-1", "--json")
        self.assertNotEqual(r.returncode, 0)


class TestAppendTo(DxmBase):
    """Zero-roundtrip dxm → file dump. One CLI call appends N events
    to a target file with no Read/Write spent on the agent side."""

    def _capture_n(self, sid: str, n: int, evt: str = "tool.invoke") -> None:
        for i in range(n):
            self._run("capture", stdin=json.dumps({
                "session_id": sid, "evt_type": evt,
                "tool_name": f"T{i}",
            }))
            time.sleep(0.002)

    def test_append_to_writes_md_lines(self):
        self._capture_n("s_at", 3)
        target = self.tmp / "out.md"
        r = self._run("append-to", str(target), "--session", "s_at")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(target.is_file())
        lines = target.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        for ln in lines:
            self.assertTrue(ln.startswith("- "))
            self.assertIn("tool.invoke", ln)

    def test_append_to_jsonl_format(self):
        self._capture_n("s_at_j", 2)
        target = self.tmp / "out.jsonl"
        r = self._run("append-to", str(target), "--session", "s_at_j",
                       "--format", "jsonl")
        self.assertEqual(r.returncode, 0)
        for ln in target.read_text().strip().splitlines():
            rec = json.loads(ln)
            self.assertEqual(rec["evt_type"], "tool.invoke")

    def test_append_to_with_header_prepends_once(self):
        self._capture_n("s_h", 2)
        target = self.tmp / "out.md"
        r = self._run("append-to", str(target), "--session", "s_h",
                       "--header", "## My header")
        self.assertEqual(r.returncode, 0)
        text = target.read_text()
        self.assertTrue(text.startswith("## My header\n"))
        # Header appears ONCE even if appended twice (it's per-call, not per-event)
        self.assertEqual(text.count("## My header"), 1)

    def test_append_to_evt_type_filter(self):
        self._capture_n("s_f", 2, evt="keep")
        self._capture_n("s_f", 2, evt="drop")
        target = self.tmp / "out.md"
        r = self._run("append-to", str(target), "--session", "s_f",
                       "--evt-type", "keep")
        self.assertEqual(r.returncode, 0)
        text = target.read_text()
        self.assertEqual(text.count("keep"), 2)
        self.assertNotIn("drop", text)

    def test_append_to_limit_caps_lines(self):
        self._capture_n("s_l", 5)
        target = self.tmp / "out.md"
        r = self._run("append-to", str(target), "--session", "s_l",
                       "--limit", "2")
        self.assertEqual(r.returncode, 0)
        lines = target.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_append_to_creates_parent_dirs(self):
        self._capture_n("s_p", 1)
        target = self.tmp / "deep" / "nested" / "out.md"
        r = self._run("append-to", str(target), "--session", "s_p")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(target.is_file())

    def test_append_to_no_match_creates_no_file(self):
        # No events captured → 0 appends → file not written
        target = self.tmp / "noop.md"
        r = self._run("append-to", str(target), "--session", "s_empty")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(target.is_file())

    def test_append_to_atomic_append_two_calls_accumulate(self):
        self._capture_n("s_a", 2)
        target = self.tmp / "out.md"
        self._run("append-to", str(target), "--session", "s_a", "--limit", "1")
        self._run("append-to", str(target), "--session", "s_a", "--limit", "1")
        # Two calls → two lines in the file
        lines = target.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)


class TestHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run([sys.executable, str(_DXM_PY), "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
