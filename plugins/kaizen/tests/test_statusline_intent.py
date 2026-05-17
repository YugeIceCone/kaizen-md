"""Tests for the statusline intent segment.

Parallels statusline_dxm — reads dxm events for the active session
and runs intent scan, emits one line for the statusline when an
event_pattern intent matches.
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
_STATUSLINE = _SCRIPTS / "statusline_intent.py"


class StatuslineIntentBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()
        self.intents_file = self.tmp / "intents.yaml"
        self._orig: dict[str, str | None] = {}
        for k, v in (
            ("HOME", str(self.fake_home)),
            ("KAIZEN_DXM_DIR", str(self.dxm_dir)),
            ("KAIZEN_INTENTS_FILE", str(self.intents_file)),
        ):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _seed_project(self, cwd: Path, sid: str):
        slug = str(cwd.resolve()).replace("/", "-")
        (self.fake_home / ".claude" / "projects" / slug).mkdir(parents=True)
        (self.fake_home / ".claude" / "projects" / slug / f"{sid}.jsonl").write_text("{}\n")

    def _seed_dxm_failures(self, sid: str, count: int):
        events_file = self.dxm_dir / f"events-{sid}.jsonl"
        with events_file.open("a") as f:
            for i in range(count):
                f.write(json.dumps({
                    "ts_unix": time.time() - 0.01 * (count - i),
                    "session_id": sid,
                    "evt_type": "PostToolUse",
                    "tool_name": "Bash",
                    "exit_code": 1,
                }) + "\n")

    def _intents(self, body: str):
        self.intents_file.write_text(body)

    def _run(self, *args: str, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_STATUSLINE), *args],
            capture_output=True, text=True, timeout=5,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )


_INTENT_FIXTURE = textwrap.dedent("""\
    version: 1
    intents:
      - id: bash-fail
        triggers:
          - kind: event_pattern
            evt_type: PostToolUse
            tool_name: Bash
            exit_code_nonzero: true
            count_at_least: 3
            window_seconds: 60
        action: {suggest: "investigate failures", confidence: 0.95}
""")


class TestSegmentOutput(StatuslineIntentBase):
    def test_emits_intent_when_pattern_matches(self):
        cwd = self.tmp / "p"
        cwd.mkdir()
        self._seed_project(cwd, "sess-int-sl")
        self._seed_dxm_failures("sess-int-sl", 3)
        self._intents(_INTENT_FIXTURE)
        r = self._run(cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.strip()
        self.assertTrue(out.startswith("intent:"),
                          f"expected intent segment, got: {out!r}")
        self.assertIn("bash-fail", out)

    def test_no_match_returns_empty(self):
        cwd = self.tmp / "p2"
        cwd.mkdir()
        self._seed_project(cwd, "sess-clean")
        self._seed_dxm_failures("sess-clean", 1)  # below threshold
        self._intents(_INTENT_FIXTURE)
        r = self._run(cwd=cwd)
        self.assertEqual(r.stdout.strip(), "")

    def test_no_session_returns_empty(self):
        cwd = self.tmp / "no-proj"
        cwd.mkdir()
        self._intents(_INTENT_FIXTURE)
        r = self._run(cwd=cwd)
        self.assertEqual(r.stdout.strip(), "")

    def test_disable_env_returns_empty(self):
        cwd = self.tmp / "p3"
        cwd.mkdir()
        self._seed_project(cwd, "sess-disable")
        self._seed_dxm_failures("sess-disable", 5)
        self._intents(_INTENT_FIXTURE)
        os.environ["KAIZEN_INTENT_DISABLE"] = "1"
        try:
            r = self._run(cwd=cwd)
            self.assertEqual(r.stdout.strip(), "")
        finally:
            del os.environ["KAIZEN_INTENT_DISABLE"]


if __name__ == "__main__":
    unittest.main()
