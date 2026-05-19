"""Tests for subagentstop_trace.py — consolidated SubagentStop helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/handlers/subagentstop_trace.py"


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


class TestEmitsGenericEvent(Base):
    def test_subagent_stop_event_always_written(self):
        self._run({"session_id": "s1"})
        events = self._events()
        generic = [e for e in events if e["evt"] == "SubagentStop"]
        self.assertEqual(len(generic), 1)


class TestEmitsDetailEventWithAgent(Base):
    def test_subagent_with_subagent_type_field(self):
        self._run({"session_id": "s1",
                    "subagent_type": "Explore",
                    "description": "find files",
                    "status": "completed"})
        events = self._events()
        detail = [e for e in events if e["evt"] == "SubagentStop-detail"]
        self.assertEqual(len(detail), 1)
        self.assertEqual(detail[0]["tool"], "Explore")
        self.assertEqual(detail[0]["data"]["agent"], "Explore")
        self.assertEqual(detail[0]["data"]["status"], "completed")


class TestNoAgentNoDetailEvent(Base):
    def test_no_agent_field_only_generic(self):
        self._run({"session_id": "s1"})
        events = self._events()
        self.assertEqual([e["evt"] for e in events], ["SubagentStop"])


class TestTraceDisabledBypass(Base):
    def test_KAIZEN_TRACE_DISABLE(self):
        env = os.environ.copy()
        env["KAIZEN_TRACE_DISABLE"] = "1"
        subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps({"session_id": "s", "subagent_type": "X"}),
            capture_output=True, text=True, timeout=5, env=env,
        )
        self.assertEqual(self._events(), [])


class TestDescriptionTruncation(Base):
    def test_long_description_truncated_to_80(self):
        long_desc = "x" * 500
        self._run({"session_id": "s", "subagent_type": "Y",
                    "description": long_desc})
        events = self._events()
        detail = next(e for e in events if e["evt"] == "SubagentStop-detail")
        self.assertEqual(len(detail["data"]["desc"]), 80)


class TestMalformedJsonGraceful(Base):
    def test_garbage_stdin_no_crash(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input="not json", capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
