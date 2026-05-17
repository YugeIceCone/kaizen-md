"""Tests for session_mode.py — the intake-state CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/session_mode.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state_path = self.tmp / "session-mode.json"
        self._orig = os.environ.get("KAIZEN_SESSION_MODE_PATH")
        os.environ["KAIZEN_SESSION_MODE_PATH"] = str(self.state_path)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_SESSION_MODE_PATH", None)
        else: os.environ["KAIZEN_SESSION_MODE_PATH"] = self._orig

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True, timeout=5,
            env=os.environ.copy(),
        )


class TestSetThenGet(Base):
    def test_set_loop_persists(self):
        r = self._run("set", "loop")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "loop")
        self.assertEqual(data["skills"], [])
        self.assertIn("set_at", data)
        self.assertTrue(self.state_path.is_file())

    def test_set_with_skills_parses_csv(self):
        r = self._run("set", "loop", "--skills", "dry,kiss,tdd")
        data = json.loads(r.stdout)
        self.assertEqual(data["skills"], ["dry", "kiss", "tdd"])

    def test_set_strips_skill_whitespace(self):
        r = self._run("set", "workflow", "--skills", " dry , kiss ,tdd ")
        data = json.loads(r.stdout)
        self.assertEqual(data["skills"], ["dry", "kiss", "tdd"])

    def test_set_session_id(self):
        r = self._run("set", "neither", "--session-id", "abc-123")
        data = json.loads(r.stdout)
        self.assertEqual(data["session_id"], "abc-123")


class TestGet(Base):
    def test_get_returns_mode_when_set(self):
        self._run("set", "workflow")
        r = self._run("get")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "workflow")

    def test_get_json_returns_full_record(self):
        self._run("set", "loop", "--skills", "dry,tdd")
        r = self._run("get", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "loop")
        self.assertEqual(data["skills"], ["dry", "tdd"])

    def test_get_unset_exit_1(self):
        r = self._run("get")
        self.assertEqual(r.returncode, 1)

    def test_get_json_unset_returns_mode_none(self):
        r = self._run("get", "--json")
        self.assertEqual(json.loads(r.stdout)["mode"], None)


class TestExists(Base):
    def test_exists_after_set(self):
        self._run("set", "loop")
        self.assertEqual(self._run("exists").returncode, 0)

    def test_exists_unset_exits_1(self):
        self.assertEqual(self._run("exists").returncode, 1)


class TestClear(Base):
    def test_clear_removes_file(self):
        self._run("set", "loop")
        self.assertTrue(self.state_path.is_file())
        r = self._run("clear")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self.state_path.is_file())

    def test_clear_when_absent_no_error(self):
        # idempotent
        r = self._run("clear")
        self.assertEqual(r.returncode, 0)


class TestInvalidMode(Base):
    def test_unknown_mode_rejected(self):
        r = self._run("set", "garbage")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.state_path.is_file())


class TestModeOverwrite(Base):
    """set replaces prior state — no implicit merge."""
    def test_second_set_overwrites_first(self):
        self._run("set", "loop", "--skills", "dry")
        self._run("set", "workflow", "--skills", "tdd")
        r = self._run("get", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "workflow")
        self.assertEqual(data["skills"], ["tdd"])


if __name__ == "__main__":
    unittest.main()
