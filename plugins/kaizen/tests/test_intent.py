"""Tests for kaizen-intent — declarative intent → action automation.

Sits on top of dxm event stream + UserPromptSubmit text matching.
Declarative rules in domain/intents.yaml map intent triggers to
suggested or auto-runnable actions.

Triggers supported (MVP):
  - phrase: regex/literal match against text input (user prompt, etc.)
  - event_pattern: dxm event_type sequence / count thresholds
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_INTENT_PY = _SCRIPTS / "intent.py"


class IntentBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.intents_path = self.tmp / "intents.yaml"
        self._orig_intents = os.environ.get("KAIZEN_INTENTS_FILE")
        os.environ["KAIZEN_INTENTS_FILE"] = str(self.intents_path)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig_intents is None: os.environ.pop("KAIZEN_INTENTS_FILE", None)
        else: os.environ["KAIZEN_INTENTS_FILE"] = self._orig_intents

    def _write_intents(self, body: str):
        self.intents_path.write_text(body, encoding="utf-8")

    def _run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_INTENT_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


_SAMPLE_INTENTS = textwrap.dedent("""\
    version: 1
    intents:
      - id: wrap-up
        description: User signals end-of-session; suggest handoff create.
        triggers:
          - { kind: phrase, pattern: "let's wrap (this )?up", case_insensitive: true }
          - { kind: phrase, pattern: "wrap.*session" }
        action:
          suggest: "Run: kaizen-handoff scaffold --session <project>"
          subcommand: handoff
          confidence: 0.9

      - id: context-pressure
        description: Context is getting tight; suggest /compact.
        triggers:
          - { kind: phrase, pattern: "context.*(high|tight|full|9[0-9]%)" }
        action:
          suggest: "Consider /compact to reclaim context window"
          subcommand: compact
          confidence: 0.85

      - id: repeated-bash-failures
        description: Several Bash failures in a row; suggest investigation.
        triggers:
          - { kind: event_pattern,
              evt_type: "PostToolUse",
              tool_name: "Bash",
              exit_code_nonzero: true,
              count_at_least: 3,
              window_seconds: 60 }
        action:
          suggest: "3+ Bash failures in 60s — investigate root cause"
          subcommand: debug
          confidence: 0.95
""")


# ─── list ────────────────────────────────────────────────────────────


class TestList(IntentBase):
    def test_lists_all_declared_intents(self):
        self._write_intents(_SAMPLE_INTENTS)
        r = self._run("list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        ids = [i["id"] for i in env["data"]["intents"]]
        self.assertEqual(set(ids),
                          {"wrap-up", "context-pressure", "repeated-bash-failures"})

    def test_empty_intents_file_is_ok(self):
        self._write_intents("version: 1\nintents: []\n")
        r = self._run("list", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["intents"], [])


# ─── match (text trigger) ────────────────────────────────────────────


class TestMatchPhrase(IntentBase):
    def setUp(self):
        super().setUp()
        self._write_intents(_SAMPLE_INTENTS)

    def test_exact_phrase_match(self):
        r = self._run("match", "--text", "let's wrap up", "--json")
        env = json.loads(r.stdout)
        matched = env["data"]["matched"]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], "wrap-up")
        self.assertGreater(matched[0]["confidence"], 0.5)

    def test_case_insensitive_match(self):
        r = self._run("match", "--text", "LET'S WRAP UP", "--json")
        env = json.loads(r.stdout)
        self.assertEqual([m["id"] for m in env["data"]["matched"]], ["wrap-up"])

    def test_no_match_returns_empty(self):
        r = self._run("match", "--text", "totally unrelated text", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["matched"], [])

    def test_match_returns_action_suggestion(self):
        r = self._run("match", "--text", "let's wrap up", "--json")
        env = json.loads(r.stdout)
        m = env["data"]["matched"][0]
        self.assertIn("suggest", m["action"])
        self.assertEqual(m["action"]["subcommand"], "handoff")

    def test_multiple_intents_can_match(self):
        # "let's wrap this up" should match wrap-up;
        # add overlapping text to also hit context-pressure
        # (use the regex "wrap.*session" intent)
        r = self._run("match", "--text",
                       "let's wrap this session up; context full", "--json")
        env = json.loads(r.stdout)
        ids = {m["id"] for m in env["data"]["matched"]}
        # Both wrap-up and context-pressure patterns apply
        self.assertIn("wrap-up", ids)
        self.assertIn("context-pressure", ids)


class TestMatchFromStdin(IntentBase):
    def test_text_can_come_from_stdin(self):
        self._write_intents(_SAMPLE_INTENTS)
        r = self._run("match", "--json", stdin="let's wrap up")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["matched"][0]["id"], "wrap-up")


# ─── match (event_pattern trigger) ───────────────────────────────────


class TestMatchEventPattern(IntentBase):
    def setUp(self):
        super().setUp()
        self._write_intents(_SAMPLE_INTENTS)

    def test_event_pattern_with_threshold_hit(self):
        events = [
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 100.0},
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 2,
              "ts_unix": 101.0},
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 102.0},
        ]
        r = self._run("match", "--events-json", json.dumps(events), "--json")
        env = json.loads(r.stdout)
        ids = {m["id"] for m in env["data"]["matched"]}
        self.assertIn("repeated-bash-failures", ids)

    def test_event_pattern_below_threshold_no_match(self):
        events = [
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 100.0},
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 101.0},
        ]
        r = self._run("match", "--events-json", json.dumps(events), "--json")
        env = json.loads(r.stdout)
        ids = {m["id"] for m in env["data"]["matched"]}
        self.assertNotIn("repeated-bash-failures", ids)

    def test_event_pattern_outside_window_no_match(self):
        events = [
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 100.0},
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 200.0},   # 100s later
            {"evt_type": "PostToolUse", "tool_name": "Bash", "exit_code": 1,
              "ts_unix": 300.0},   # 200s later, well outside 60s window
        ]
        r = self._run("match", "--events-json", json.dumps(events), "--json")
        env = json.loads(r.stdout)
        ids = {m["id"] for m in env["data"]["matched"]}
        self.assertNotIn("repeated-bash-failures", ids)


# ─── envelope shape + validation ─────────────────────────────────────


class TestEnvelope(IntentBase):
    def test_envelope_has_canonical_meta(self):
        self._write_intents(_SAMPLE_INTENTS)
        r = self._run("match", "--text", "let's wrap up", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["kaizen"]["tool"], "kaizen-intent")
        self.assertIn("data", env)

    def test_intents_file_missing_errors(self):
        os.environ["KAIZEN_INTENTS_FILE"] = str(self.tmp / "does-not-exist.yaml")
        r = self._run("list", "--json")
        self.assertNotEqual(r.returncode, 0)


class TestSuggest(IntentBase):
    """`suggest` returns the BEST match's action — the top-confidence
    intent. Used by other tools (e.g. statusline) for one-line hints."""

    def test_suggest_picks_highest_confidence(self):
        # Two matching intents with different confidences
        self._write_intents(textwrap.dedent("""\
            version: 1
            intents:
              - id: low
                triggers: [{kind: phrase, pattern: "foo"}]
                action: {suggest: "low-conf", confidence: 0.4}
              - id: high
                triggers: [{kind: phrase, pattern: "foo"}]
                action: {suggest: "high-conf", confidence: 0.9}
        """))
        r = self._run("suggest", "--text", "foo bar", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["intent"]["id"], "high")
        self.assertEqual(env["data"]["intent"]["action"]["suggest"],
                          "high-conf")

    def test_suggest_no_match_returns_null(self):
        self._write_intents(_SAMPLE_INTENTS)
        r = self._run("suggest", "--text", "blah", "--json")
        env = json.loads(r.stdout)
        self.assertIsNone(env["data"].get("intent"))


class TestHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run([sys.executable, str(_INTENT_PY), "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
