"""Tests for kaizen-intent scan + intent-userprompt.sh hook + schemas.

scan: pull last N seconds of events from dxm + run match against them.
hook: fire kaizen-intent suggest on user-prompt text; print system reminder when match.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_INTENT_PY = _KZ_DIR / "scripts/intent" / "intent.py"
_DXM_PY = _KZ_DIR / "scripts" / "observe" / "dxm.py"
_HOOK = _KZ_DIR / "hooks/claude/intent-userprompt.sh"


class IntentScanBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.intents_path = self.tmp / "intents.yaml"
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()

        self._orig: dict[str, str | None] = {}
        for k, v in (("KAIZEN_INTENTS_FILE", str(self.intents_path)),
                      ("KAIZEN_DXM_DIR", str(self.dxm_dir))):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, orig in self._orig.items():
            if orig is None: os.environ.pop(k, None)
            else: os.environ[k] = orig

    def _intents(self, body: str):
        self.intents_path.write_text(body, encoding="utf-8")

    def _dxm(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DXM_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def _intent(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_INTENT_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


_INTENT_FIXTURE = textwrap.dedent("""\
    version: 1
    intents:
      - id: bash-failure-pattern
        triggers:
          - kind: event_pattern
            evt_type: PostToolUse
            tool_name: Bash
            exit_code_nonzero: true
            count_at_least: 2
            window_seconds: 60
        action: {suggest: "investigate Bash failures", confidence: 0.95}
""")


# ─── scan (dxm-driven matching) ──────────────────────────────────────


class TestScan(IntentScanBase):
    def test_scan_hits_when_dxm_has_matching_events(self):
        self._intents(_INTENT_FIXTURE)
        # Seed dxm with 2 Bash failures in the last second
        sid = "scan-sess"
        for _ in range(2):
            self._dxm("capture", stdin=json.dumps({
                "session_id": sid, "evt_type": "PostToolUse",
                "tool_name": "Bash", "exit_code": 1}))
            time.sleep(0.01)
        r = self._intent("scan", "--session", sid, "--back", "60", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        ids = {m["id"] for m in env["data"]["matched"]}
        self.assertIn("bash-failure-pattern", ids)

    def test_scan_no_match_when_dxm_empty(self):
        self._intents(_INTENT_FIXTURE)
        r = self._intent("scan", "--session", "empty-sess",
                          "--back", "60", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["matched"], [])

    def test_scan_back_parameter_filters_window(self):
        self._intents(_INTENT_FIXTURE)
        sid = "old-sess"
        # Two failures, then sleep 0.3, then ask for events in last 0.1s
        for _ in range(2):
            self._dxm("capture", stdin=json.dumps({
                "session_id": sid, "evt_type": "PostToolUse",
                "tool_name": "Bash", "exit_code": 1}))
            time.sleep(0.01)
        time.sleep(0.3)
        r = self._intent("scan", "--session", sid, "--back", "0.1", "--json")
        env = json.loads(r.stdout)
        # No events in last 100ms → no match
        ids = {m["id"] for m in env["data"]["matched"]}
        self.assertNotIn("bash-failure-pattern", ids)


# ─── intent-userprompt.sh hook ───────────────────────────────────────


class TestIntentUserPromptHook(IntentScanBase):
    def test_hook_emits_system_reminder_on_match(self):
        self._intents(textwrap.dedent("""\
            version: 1
            intents:
              - id: wrap-up
                triggers:
                  - {kind: phrase, pattern: "wrap (this )?up", case_insensitive: true}
                action: {suggest: "scaffold a handoff", confidence: 0.9}
        """))
        # CC's UserPromptSubmit hook event JSON shape
        event = {
            "session_id": "sess-x",
            "prompt": "let's wrap up this session and move on",
        }
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(event), capture_output=True, text=True,
            timeout=10, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # The hook prints a JSON decision object — when match, embeds
        # a systemMessage carrying the suggestion text
        try:
            decision = json.loads(r.stdout.strip())
        except json.JSONDecodeError:
            self.fail(f"hook stdout not JSON: {r.stdout!r}")
        sys_msg = decision.get("systemMessage") or ""
        self.assertIn("scaffold a handoff", sys_msg)
        self.assertIn("wrap-up", sys_msg)

    def test_hook_emits_empty_when_no_match(self):
        self._intents(textwrap.dedent("""\
            version: 1
            intents:
              - id: never-fires
                triggers:
                  - {kind: phrase, pattern: "TOTALLY_UNRELATED_PATTERN_XYZ"}
                action: {suggest: "...", confidence: 0.5}
        """))
        event = {"session_id": "sess-y", "prompt": "do the thing"}
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(event), capture_output=True, text=True,
            timeout=10, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)
        # Empty decision = {}
        self.assertEqual(r.stdout.strip(), "{}")

    def test_hook_respects_disable_env(self):
        self._intents(textwrap.dedent("""\
            version: 1
            intents:
              - id: would-match
                triggers: [{kind: phrase, pattern: "anything"}]
                action: {suggest: "...", confidence: 0.9}
        """))
        os.environ["KAIZEN_INTENT_DISABLE"] = "1"
        try:
            event = {"session_id": "s", "prompt": "anything"}
            r = subprocess.run(
                ["bash", str(_HOOK)],
                input=json.dumps(event), capture_output=True, text=True,
                timeout=10, env=os.environ.copy(),
            )
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "{}")
        finally:
            del os.environ["KAIZEN_INTENT_DISABLE"]

    def test_hook_handles_malformed_input(self):
        # Hook must never block the host flow on bad input
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input="not-json", capture_output=True, text=True,
            timeout=10, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)


# ─── output schemas exist + valid ────────────────────────────────────


class TestIntentSchemasPresent(unittest.TestCase):
    def test_match_out_schema_exists(self):
        p = _KZ_DIR / "skills/intent/domain/schemas/match-out.schema.json"
        self.assertTrue(p.is_file(), f"missing {p}")
        json.loads(p.read_text())

    def test_suggest_out_schema_exists(self):
        p = _KZ_DIR / "skills/intent/domain/schemas/suggest-out.schema.json"
        self.assertTrue(p.is_file(), f"missing {p}")
        json.loads(p.read_text())

    def test_list_out_schema_exists(self):
        p = _KZ_DIR / "skills/intent/domain/schemas/list-out.schema.json"
        self.assertTrue(p.is_file(), f"missing {p}")
        json.loads(p.read_text())

    def test_match_in_schema_exists(self):
        p = _KZ_DIR / "skills/intent/domain/schemas/match-in.schema.json"
        self.assertTrue(p.is_file(), f"missing {p}")
        json.loads(p.read_text())


if __name__ == "__main__":
    unittest.main()
