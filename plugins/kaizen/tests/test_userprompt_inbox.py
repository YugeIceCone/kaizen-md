"""Tests for userprompt_inbox.py — consolidated UserPromptSubmit
inbox capture helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/handlers/userprompt_inbox.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.inbox = self.tmp / "inbox"
        self._orig = os.environ.get("KAIZEN_INBOX_DIR")
        os.environ["KAIZEN_INBOX_DIR"] = str(self.inbox)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_INBOX_DIR", None)
        else: os.environ["KAIZEN_INBOX_DIR"] = self._orig

    def _run(self, payload: dict,
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True, text=True,
            timeout=10, env=env,
        )

    def _captured(self) -> list[Path]:
        if not self.inbox.is_dir():
            return []
        return sorted(p for p in self.inbox.iterdir()
                      if p.suffix == ".json" and not p.name.startswith("."))


class TestCapturesPromptIntoInbox(Base):
    def test_creates_one_json_per_prompt(self):
        r = self._run({"prompt": "hello world", "session_id": "s1"})
        self.assertEqual(r.returncode, 0)
        captured = self._captured()
        self.assertEqual(len(captured), 1)
        data = json.loads(captured[0].read_text())
        self.assertEqual(data["prompt"], "hello world")
        self.assertEqual(data["session_id"], "s1")
        self.assertFalse(data["drained"])


class TestPromptFieldFallbacks(Base):
    def test_user_prompt_field(self):
        r = self._run({"user_prompt": "via user_prompt", "session_id": "s"})
        captured = self._captured()
        self.assertEqual(json.loads(captured[0].read_text())["prompt"],
                          "via user_prompt")

    def test_message_field(self):
        r = self._run({"message": "via message"})
        captured = self._captured()
        self.assertEqual(json.loads(captured[0].read_text())["prompt"],
                          "via message")


class TestSetsTurnStarter(Base):
    def test_first_prompt_sets_sentinel(self):
        self._run({"prompt": "first", "session_id": "s"})
        sentinel = self.inbox / ".current-turn"
        self.assertTrue(sentinel.exists())
        captured = self._captured()
        sentinel_data = json.loads(sentinel.read_text())
        self.assertEqual(sentinel_data["path"], str(captured[0]))

    def test_second_prompt_does_not_overwrite_sentinel(self):
        # Simulates mid-turn user message — should be captured but
        # the sentinel still points at the FIRST prompt
        self._run({"prompt": "first turn-starter", "session_id": "s"})
        first_captured = self._captured()[0]
        self._run({"prompt": "second mid-turn", "session_id": "s"})
        sentinel = self.inbox / ".current-turn"
        self.assertEqual(json.loads(sentinel.read_text())["path"],
                          str(first_captured))


class TestEmptyPromptNoOp(Base):
    def test_no_prompt_field_skips(self):
        r = self._run({"session_id": "s"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self._captured(), [])

    def test_empty_prompt_skips(self):
        r = self._run({"prompt": "", "session_id": "s"})
        self.assertEqual(self._captured(), [])


class TestDisableBypass(Base):
    def test_KAIZEN_INBOX_DISABLE_no_op(self):
        r = self._run({"prompt": "hi", "session_id": "s"},
                       env_extra={"KAIZEN_INBOX_DISABLE": "1"})
        self.assertEqual(self._captured(), [])


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
