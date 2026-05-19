"""Tests for stop_backlog_reminder.py — consolidated Stop-hook helper."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/handlers/stop_backlog_reminder.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Init a git repo
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        self._inflight_orig = os.environ.pop("KAIZEN_STOP_BLOCK_INFLIGHT", None)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._inflight_orig is not None:
            os.environ["KAIZEN_STOP_BLOCK_INFLIGHT"] = self._inflight_orig

    def _setup_backlog(self, items: list[dict]):
        (self.tmp / ".kaizen.toml").write_text(
            'backlog_path = ".kaizen/workflow/backlog.md"\n')
        (self.tmp / ".kaizen" / "workflow").mkdir(parents=True)
        (self.tmp / ".kaizen" / "workflow" / "backlog.json").write_text(
            json.dumps({"items": items}))

    def _run(self, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(_SCRIPT)],
            capture_output=True, text=True, timeout=10,
            cwd=str(self.tmp), env=env,
        )


class TestNoInFlightEmptyOutput(Base):
    def test_returns_empty_when_no_inflight(self):
        self._setup_backlog([
            {"id": "BK-1", "title": "x", "section": "next_up"},
        ])
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


class TestSoftReminder(Base):
    def test_inflight_produces_systemMessage(self):
        self._setup_backlog([
            {"id": "BK-1", "title": "do thing", "section": "in_flight"},
            {"id": "BK-2", "title": "later",    "section": "next_up"},
        ])
        r = self._run()
        out = json.loads(r.stdout)
        self.assertIn("systemMessage", out)
        self.assertIn("1 in_flight", out["systemMessage"])
        self.assertIn("BK-1: do thing", out["systemMessage"])
        self.assertNotIn("decision", out)


class TestHardBlock(Base):
    def test_KAIZEN_STOP_BLOCK_INFLIGHT_returns_block_decision(self):
        self._setup_backlog([
            {"id": "BK-1", "title": "do thing", "section": "in_flight"},
        ])
        r = self._run(env_extra={"KAIZEN_STOP_BLOCK_INFLIGHT": "1"})
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("1 in_flight", out["reason"])


class TestNoBacklog(Base):
    def test_no_kaizen_toml_returns_empty(self):
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")

    def test_no_backlog_json_returns_empty(self):
        (self.tmp / ".kaizen.toml").write_text(
            'backlog_path = ".kaizen/workflow/backlog.md"\n')
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


class TestNotGitRepo(Base):
    def test_outside_git_repo_returns_empty(self):
        # Override cwd to a non-git dir
        outside = self.tmp.parent / "_not_a_repo_dir"
        outside.mkdir(exist_ok=True)
        try:
            r = subprocess.run(
                [sys.executable, str(_SCRIPT)],
                capture_output=True, text=True, timeout=10,
                cwd=str(outside), env=os.environ.copy(),
            )
            self.assertEqual(r.stdout.strip(), "{}")
        finally:
            outside.rmdir()


class TestDisableBypass(Base):
    def test_KAIZEN_BACKLOG_DISABLE_returns_empty(self):
        self._setup_backlog([
            {"id": "BK-1", "title": "x", "section": "in_flight"},
        ])
        r = self._run(env_extra={"KAIZEN_BACKLOG_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestMultipleInFlight(Base):
    def test_count_and_titles_correct(self):
        self._setup_backlog([
            {"id": f"BK-{i}", "title": f"task {i}", "section": "in_flight"}
            for i in range(1, 4)
        ])
        r = self._run()
        out = json.loads(r.stdout)
        msg = out["systemMessage"]
        self.assertIn("3 in_flight", msg)
        self.assertIn("BK-1: task 1", msg)
        self.assertIn("BK-3: task 3", msg)


class TestMalformedBacklogGraceful(Base):
    def test_invalid_json_returns_empty(self):
        (self.tmp / ".kaizen.toml").write_text(
            'backlog_path = ".kaizen/workflow/backlog.md"\n')
        (self.tmp / ".kaizen" / "workflow").mkdir(parents=True)
        (self.tmp / ".kaizen" / "workflow" / "backlog.json").write_text("not json")
        r = self._run()
        self.assertEqual(r.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
