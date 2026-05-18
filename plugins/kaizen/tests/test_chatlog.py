"""Tests for kaizen-chatlog — trigger-rule-driven CC transcript slicer.

Per user 2026-05-18 (sid 9f4c8972) — "new system for docs: automated
session chat log input and output commits based on tracable triggers."

Designed during this session as the MVP layer. Scope:
  IN  — read a CC transcript .jsonl, walk events, match each event
        against a list of trigger rules. For each match, capture the
        event + N before + N after as a "slice".
  OUT — per-rule .jsonl files written to <out_dir>/<rule_id>.jsonl.
        Each line is one slice (array of events as a single JSON line).

Trigger types (v1 — 3 KISS shapes):
  event_type           — direct match on event["type"]
  user_keyword         — user-message body regex match
  assistant_tool_use   — assistant turn that calls a specific tool

Action (v1 — 1 KISS shape):
  capture {before: N, after: N}  — N events before + match + N after
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
_CHATLOG = _KZ / "skills/workflow/scripts/chatlog.py"

# Direct import for unit tests of pure functions
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
from _chatlog import match_event, extract_slice, slice_transcript  # noqa: E402


# ─── Fixture events ────────────────────────────────────────────────────

def _user_event(uid: str, text: str) -> dict:
    return {
        "uuid": uid, "type": "user",
        "message": {"role": "user", "content": text},
        "timestamp": "2026-05-18T20:00:00Z",
    }


def _assistant_event(uid: str, text: str, tool_uses=()) -> dict:
    content = [{"type": "text", "text": text}]
    for tu in tool_uses:
        content.append({"type": "tool_use", "name": tu, "input": {}})
    return {
        "uuid": uid, "type": "assistant",
        "message": {"role": "assistant", "content": content},
        "timestamp": "2026-05-18T20:00:01Z",
    }


def _attachment_event(uid: str, hook: str) -> dict:
    return {
        "uuid": uid, "type": "attachment",
        "attachment": {"type": "hook_success", "hookName": hook},
        "timestamp": "2026-05-18T20:00:02Z",
    }


# ─── match_event ────────────────────────────────────────────────────────

class TestMatchEventType(unittest.TestCase):
    def test_matches_event_type(self):
        e = _attachment_event("u1", "SessionStart")
        rule = {"trigger": {"type": "event_type", "event_type": "attachment"}}
        self.assertTrue(match_event(e, rule))

    def test_no_match_on_event_type_mismatch(self):
        e = _user_event("u1", "hi")
        rule = {"trigger": {"type": "event_type", "event_type": "attachment"}}
        self.assertFalse(match_event(e, rule))


class TestMatchUserKeyword(unittest.TestCase):
    def test_matches_keyword(self):
        e = _user_event("u1", "the gate failed because of X")
        rule = {"trigger": {"type": "user_keyword", "pattern": r"gate.*fail"}}
        self.assertTrue(match_event(e, rule))

    def test_keyword_case_insensitive(self):
        e = _user_event("u1", "HEARTBEAT just fired")
        rule = {"trigger": {"type": "user_keyword", "pattern": r"heartbeat"}}
        self.assertTrue(match_event(e, rule))

    def test_no_match_on_keyword_miss(self):
        e = _user_event("u1", "hello world")
        rule = {"trigger": {"type": "user_keyword", "pattern": r"goodbye"}}
        self.assertFalse(match_event(e, rule))

    def test_assistant_event_does_not_match_user_keyword(self):
        e = _assistant_event("u1", "some response")
        rule = {"trigger": {"type": "user_keyword", "pattern": r"response"}}
        self.assertFalse(match_event(e, rule))


class TestMatchAssistantToolUse(unittest.TestCase):
    def test_matches_tool_name(self):
        e = _assistant_event("u1", "calling tool", tool_uses=["Bash"])
        rule = {"trigger": {"type": "assistant_tool_use", "tool_name": "Bash"}}
        self.assertTrue(match_event(e, rule))

    def test_no_match_on_different_tool(self):
        e = _assistant_event("u1", "calling tool", tool_uses=["Read"])
        rule = {"trigger": {"type": "assistant_tool_use", "tool_name": "Bash"}}
        self.assertFalse(match_event(e, rule))

    def test_user_event_does_not_match_tool_use(self):
        e = _user_event("u1", "run something")
        rule = {"trigger": {"type": "assistant_tool_use", "tool_name": "Bash"}}
        self.assertFalse(match_event(e, rule))


class TestMatchGraceful(unittest.TestCase):
    def test_missing_message_field_no_crash(self):
        e = {"uuid": "u1", "type": "user"}  # no message
        rule = {"trigger": {"type": "user_keyword", "pattern": r"x"}}
        self.assertFalse(match_event(e, rule))

    def test_unknown_trigger_type_returns_false(self):
        e = _user_event("u1", "hi")
        rule = {"trigger": {"type": "made_up_trigger", "pattern": "x"}}
        self.assertFalse(match_event(e, rule))


# ─── extract_slice ──────────────────────────────────────────────────────

class TestExtractSlice(unittest.TestCase):
    def setUp(self):
        self.events = [
            _user_event("u0", "first"),
            _assistant_event("a1", "second"),
            _user_event("u2", "match"),
            _assistant_event("a3", "fourth"),
            _user_event("u4", "fifth"),
        ]

    def test_extract_window_0_returns_just_match(self):
        s = extract_slice(self.events, idx=2, before=0, after=0)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["uuid"], "u2")

    def test_extract_window_1_1_returns_3(self):
        s = extract_slice(self.events, idx=2, before=1, after=1)
        self.assertEqual([e["uuid"] for e in s], ["a1", "u2", "a3"])

    def test_extract_window_clamps_at_start(self):
        s = extract_slice(self.events, idx=0, before=5, after=0)
        self.assertEqual([e["uuid"] for e in s], ["u0"])

    def test_extract_window_clamps_at_end(self):
        s = extract_slice(self.events, idx=4, before=0, after=5)
        self.assertEqual([e["uuid"] for e in s], ["u4"])

    def test_extract_large_window_returns_all(self):
        s = extract_slice(self.events, idx=2, before=10, after=10)
        self.assertEqual(len(s), 5)


# ─── slice_transcript ───────────────────────────────────────────────────

class TestSliceTranscript(unittest.TestCase):
    def setUp(self):
        self.events = [
            _user_event("u0", "casual greeting"),
            _assistant_event("a1", "running build", tool_uses=["Bash"]),
            _user_event("u2", "the gate failed yesterday"),
            _assistant_event("a3", "investigating"),
            _user_event("u4", "another gate failure"),
        ]

    def test_single_rule_collects_matches(self):
        rules = [{"id": "gate_issues",
                  "trigger": {"type": "user_keyword", "pattern": r"gate.*fail"},
                  "capture": {"before": 0, "after": 1}}]
        out = slice_transcript(self.events, rules)
        self.assertIn("gate_issues", out)
        self.assertEqual(len(out["gate_issues"]), 2)
        # Each slice is a list of events
        first_slice = out["gate_issues"][0]
        self.assertEqual(first_slice[0]["uuid"], "u2")

    def test_multiple_rules_independent(self):
        rules = [
            {"id": "user_words",
             "trigger": {"type": "user_keyword", "pattern": r"gate"},
             "capture": {"before": 0, "after": 0}},
            {"id": "bash_calls",
             "trigger": {"type": "assistant_tool_use", "tool_name": "Bash"},
             "capture": {"before": 0, "after": 0}},
        ]
        out = slice_transcript(self.events, rules)
        self.assertEqual(len(out["user_words"]), 2)
        self.assertEqual(len(out["bash_calls"]), 1)

    def test_no_matches_produces_empty_list(self):
        rules = [{"id": "nothing",
                  "trigger": {"type": "user_keyword", "pattern": r"unicorn"},
                  "capture": {"before": 0, "after": 0}}]
        out = slice_transcript(self.events, rules)
        self.assertEqual(out["nothing"], [])

    def test_idempotent_on_same_input(self):
        rules = [{"id": "x",
                  "trigger": {"type": "user_keyword", "pattern": r"casual"},
                  "capture": {"before": 0, "after": 0}}]
        a = slice_transcript(self.events, rules)
        b = slice_transcript(self.events, rules)
        self.assertEqual(a, b)


# ─── CLI integration ────────────────────────────────────────────────────

class TestChatlogCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Write a fixture transcript
        self.transcript = self.tmp / "session.jsonl"
        events = [
            _user_event("u0", "hello"),
            _user_event("u1", "the gate failed"),
            _assistant_event("a1", "fixing"),
        ]
        self.transcript.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8")
        # Write rules
        self.rules = self.tmp / "rules.json"
        self.rules.write_text(json.dumps({
            "rules": [
                {"id": "gate_failures",
                 "trigger": {"type": "user_keyword", "pattern": r"gate.*fail"},
                 "capture": {"before": 0, "after": 1}},
            ]}), encoding="utf-8")
        self.out = self.tmp / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_CHATLOG), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_slice_writes_per_rule_file(self):
        r = self._run("slice", "--transcript", str(self.transcript),
                       "--rules", str(self.rules),
                       "--out", str(self.out))
        self.assertEqual(r.returncode, 0, r.stderr)
        out_file = self.out / "gate_failures.jsonl"
        self.assertTrue(out_file.is_file())
        lines = [l for l in out_file.read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)  # 1 match
        sl = json.loads(lines[0])
        self.assertEqual([e["uuid"] for e in sl], ["u1", "a1"])

    def test_slice_json_output_reports_counts(self):
        r = self._run("slice", "--transcript", str(self.transcript),
                       "--rules", str(self.rules),
                       "--out", str(self.out),
                       "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["counts"]["gate_failures"], 1)

    def test_slice_missing_transcript_fails(self):
        r = self._run("slice", "--transcript", str(self.tmp / "nope.jsonl"),
                       "--rules", str(self.rules),
                       "--out", str(self.out))
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
