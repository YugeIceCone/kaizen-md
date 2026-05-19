"""Tests for pretooluse_trace.py — consolidated PreToolUse hot path.

Replaces the prior 4-spawn shell pattern with one python3 invocation
that does parse + ident-extract + trace.append_event in one process.

Verifies:
  - Event records the correct shape per tool type
  - Bash is skipped (already traced by pretooluse-bash-gate.sh)
  - Malformed JSON is handled gracefully
  - Disabled metrics → no-op (delegated to trace.append_event)
  - MCP tool ident is the tool name itself
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
_SCRIPT = _KZ_DIR / "scripts/handlers/pretooluse_trace.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Sandbox the trace dir
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
        # trace.py writes to trace/events.jsonl under KAIZEN_TRACE_DIR
        f = self.tmp / "trace" / "events.jsonl"
        if not f.is_file(): return []
        return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


class TestSkipsBash(Base):
    def test_bash_tool_emits_no_trace(self):
        r = self._run({"tool_name": "Bash",
                        "tool_input": {"command": "ls"},
                        "session_id": "sid-bash"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self._events(), [],
                          "Bash should be skipped (handled by bash-gate hook)")


class TestSkipsEmptyToolName(Base):
    def test_empty_tool_name_no_op(self):
        r = self._run({"tool_input": {}, "session_id": "sid"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self._events(), [])


class TestSkillExtraction(Base):
    def test_skill_ident_from_skill_field(self):
        r = self._run({"tool_name": "Skill",
                        "tool_input": {"skill": "writing-plans"},
                        "session_id": "sid-s"})
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool"], "Skill")
        self.assertEqual(events[0]["evt"], "PreToolUse-Skill")
        self.assertEqual(events[0]["sid"], "sid-s")
        self.assertEqual(events[0]["data"]["ident"], "writing-plans")


class TestFileToolExtraction(Base):
    def test_read_extracts_file_path(self):
        r = self._run({"tool_name": "Read",
                        "tool_input": {"file_path": "/tmp/foo.py"},
                        "session_id": "sid-r"})
        events = self._events()
        self.assertEqual(events[0]["data"]["ident"], "/tmp/foo.py")

    def test_edit_extracts_file_path(self):
        self._run({"tool_name": "Edit",
                    "tool_input": {"file_path": "/tmp/bar.py", "old_string": "x"},
                    "session_id": "sid-e"})
        self.assertEqual(self._events()[0]["data"]["ident"], "/tmp/bar.py")


class TestGrepExtraction(Base):
    def test_grep_pattern(self):
        r = self._run({"tool_name": "Grep",
                        "tool_input": {"pattern": "def my_func"},
                        "session_id": "sid-g"})
        self.assertEqual(self._events()[0]["data"]["ident"], "def my_func")


class TestMcpToolUsesNameAsIdent(Base):
    def test_mcp_tool_ident_is_tool_name(self):
        r = self._run({"tool_name": "mcp__plugin_kaizen_kaizen__backlog_list",
                        "tool_input": {"limit": 10},
                        "session_id": "sid-m"})
        events = self._events()
        self.assertEqual(events[0]["data"]["ident"],
                          "mcp__plugin_kaizen_kaizen__backlog_list")


class TestIdentTruncation(Base):
    def test_long_ident_truncated_to_120(self):
        long_pattern = "x" * 500
        r = self._run({"tool_name": "Grep",
                        "tool_input": {"pattern": long_pattern},
                        "session_id": "sid-l"})
        self.assertEqual(len(self._events()[0]["data"]["ident"]), 120)


class TestNoSessionIdStillTraces(Base):
    """session_id absent (rare) — should still emit event without sid field."""
    def test_no_session_id(self):
        self._run({"tool_name": "Read",
                    "tool_input": {"file_path": "/tmp/a"}})
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertNotIn("sid", events[0])


class TestMalformedStdinGracefulNoOp(Base):
    def test_malformed_json_does_not_crash(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input="not-json", capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self._events(), [])


class TestInjectionResistance(Base):
    """Defense check: malicious idents can't escape now because we
    never interpolate into Python source — values go through json
    parsing + dict access only."""
    def test_triple_quote_payload_does_not_execute(self):
        canary = self.tmp / "PWNED"
        malicious = (
            f"foo'''); open('{canary}', 'w').write('pwned'); print('''"
        )
        self._run({"tool_name": "Grep",
                    "tool_input": {"pattern": malicious},
                    "session_id": "sid-i"})
        self.assertFalse(canary.exists())
        # Event still recorded — payload safely stored as a string
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertIn("foo", events[0]["data"]["ident"])


if __name__ == "__main__":
    unittest.main()
