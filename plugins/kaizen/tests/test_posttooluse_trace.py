"""Tests for posttooluse_trace.py — consolidated PostToolUse hot path.
Mirror of test_pretooluse_trace.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/posttooluse_trace.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_TRACE_DIR")
        os.environ["KAIZEN_TRACE_DIR"] = str(self.tmp / "trace")

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_TRACE_DIR", None)
        else: os.environ["KAIZEN_TRACE_DIR"] = self._orig

    def _run(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True, text=True,
            timeout=10, env=os.environ.copy(),
        )

    def _events(self) -> list[dict]:
        f = self.tmp / "trace" / "events.jsonl"
        if not f.is_file(): return []
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


class TestSkipBash(Base):
    def test_bash_skipped(self):
        self._run({"tool_name": "Bash", "session_id": "s"})
        self.assertEqual(self._events(), [])


class TestSuccessRecorded(Base):
    def test_ok_result_in_data(self):
        self._run({"tool_name": "Read", "session_id": "s",
                    "tool_response": {"content": "ok"}})
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["evt"], "PostToolUse-Read")
        self.assertEqual(events[0]["data"]["result"], "ok")


class TestErrorRecorded(Base):
    def test_isError_marked(self):
        self._run({"tool_name": "Edit", "session_id": "s",
                    "tool_response": {"isError": True, "error": "boom"}})
        events = self._events()
        self.assertEqual(events[0]["data"]["result"], "err")


class TestDurationFromTopLevel(Base):
    def test_top_level_duration_ms(self):
        self._run({"tool_name": "Glob", "session_id": "s",
                    "duration_ms": 42,
                    "tool_response": {"matches": []}})
        events = self._events()
        self.assertEqual(events[0]["ms"], 42)


class TestDurationFromNested(Base):
    def test_nested_duration_ms(self):
        self._run({"tool_name": "Glob", "session_id": "s",
                    "tool_response": {"duration_ms": 99}})
        events = self._events()
        self.assertEqual(events[0]["ms"], 99)


class TestNoDurationOmitted(Base):
    def test_missing_duration_no_ms_field(self):
        self._run({"tool_name": "Read", "session_id": "s",
                    "tool_response": {}})
        events = self._events()
        self.assertNotIn("ms", events[0])


class TestNoSessionIdStillTraces(Base):
    def test_no_sid(self):
        self._run({"tool_name": "Read",
                    "tool_response": {"content": "x"}})
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertNotIn("sid", events[0])


class TestMalformedJsonGraceful(Base):
    def test_malformed_no_crash(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input="garbage", capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
