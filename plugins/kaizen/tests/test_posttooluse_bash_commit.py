"""Tests for posttooluse_bash_commit.py — backlog-commit matcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/handlers/posttooluse_bash_commit.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._inflight_orig = os.environ.pop("KAIZEN_BACKLOG_COMMIT_DISABLE", None)
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                         "commit", "--allow-empty", "-q", "-m", "init"],
                        cwd=self.tmp, check=True)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._inflight_orig is not None:
            os.environ["KAIZEN_BACKLOG_COMMIT_DISABLE"] = self._inflight_orig

    def _setup_backlog(self, items: list[dict]):
        (self.tmp / ".kaizen.toml").write_text(
            'backlog_path = ".kaizen/workflow/backlog.md"\n')
        (self.tmp / ".kaizen" / "workflow").mkdir(parents=True)
        (self.tmp / ".kaizen" / "workflow" / "backlog.json").write_text(
            json.dumps({"items": items}))

    def _add_commit(self, msg: str):
        (self.tmp / "f").write_text("x")
        subprocess.run(["git", "add", "-A"], cwd=self.tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                         "commit", "-q", "-m", msg],
                        cwd=self.tmp, check=True)

    def _run(self, event: dict,
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_extra: env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps(event),
            capture_output=True, text=True, timeout=10,
            cwd=str(self.tmp), env=env,
        )


class TestNonGitCommitSkipped(Base):
    def test_non_git_command_no_op(self):
        r = self._run({"tool_input": {"command": "ls -la"}})
        self.assertEqual(r.stdout.strip(), "{}")


class TestIdMatch(Base):
    def test_commit_mentioning_bk_id_surfaces_suggestion(self):
        self._setup_backlog([
            {"id": "BK-99", "title": "do the thing", "section": "in_flight"},
        ])
        self._add_commit("feat(x): wire up BK-99 logic")
        r = self._run({"tool_input": {"command": "git commit -m 'feat(x): wire up BK-99 logic'"}})
        out = json.loads(r.stdout)
        self.assertIn("hookSpecificOutput", out)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("BK-99", ctx)
        self.assertIn("id-match", ctx)


class TestTitleMatch(Base):
    def test_commit_referencing_title_phrase(self):
        self._setup_backlog([
            {"id": "BK-12",
              "title": "context-window peak-aware reader implementation",
              "section": "in_flight"},
        ])
        self._add_commit("context-window peak-aware reader implementation lands")
        r = self._run({"tool_input": {"command": "git commit -m 'msg'"}})
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("title-match", ctx)


class TestErrorResultSkipped(Base):
    def test_failed_commit_no_suggestion(self):
        self._setup_backlog([
            {"id": "BK-1", "title": "x", "section": "in_flight"},
        ])
        r = self._run({"tool_input": {"command": "git commit -m 'x'"},
                        "tool_result": {"type": "error"}})
        self.assertEqual(r.stdout.strip(), "{}")


class TestNoBacklogNoOp(Base):
    def test_missing_kaizen_toml(self):
        self._add_commit("feat: thing")
        r = self._run({"tool_input": {"command": "git commit -m x"}})
        self.assertEqual(r.stdout.strip(), "{}")


class TestNoInFlightMatchesNoOp(Base):
    def test_only_next_up_items(self):
        self._setup_backlog([
            {"id": "BK-1", "title": "x", "section": "next_up"},
        ])
        self._add_commit("mentions BK-1 but it's not in_flight")
        r = self._run({"tool_input": {"command": "git commit -m 'msg'"}})
        self.assertEqual(r.stdout.strip(), "{}")


class TestDisableBypass(Base):
    def test_KAIZEN_BACKLOG_COMMIT_DISABLE(self):
        self._setup_backlog([
            {"id": "BK-9", "title": "x", "section": "in_flight"},
        ])
        self._add_commit("BK-9 closed")
        r = self._run({"tool_input": {"command": "git commit -m x"}},
                       env_extra={"KAIZEN_BACKLOG_COMMIT_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestMalformedJsonGraceful(Base):
    def test_malformed_no_crash(self):
        r = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input="garbage", capture_output=True, text=True,
            timeout=5, cwd=str(self.tmp), env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
