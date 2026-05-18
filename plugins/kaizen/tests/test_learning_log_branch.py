"""Tests for kaizen-learn branch-aware capture + filter.

Every entry auto-captures the git branch of the cwd when present.
List can filter by branch — enables per-feature history isolation.
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
_LEARN_PY = _KZ_DIR / "skills/workflow/scripts/learning_log.py"


class _BranchBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Sandbox the sink
        self.sink = self.tmp / "sink"
        self.sink.mkdir()
        self._orig_sink = os.environ.get("KAIZEN_LEARNING_DIR")
        os.environ["KAIZEN_LEARNING_DIR"] = str(self.sink)
        # Make a tiny git repo
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for cmd in (
            ["git", "init", "-q", "-b", "master"],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(cmd, cwd=str(self.repo), check=True,
                            capture_output=True)
        (self.repo / "f.txt").write_text("init")
        subprocess.run(["git", "add", "f.txt"], cwd=str(self.repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                        cwd=str(self.repo), check=True, capture_output=True)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig_sink is None:
            os.environ.pop("KAIZEN_LEARNING_DIR", None)
        else:
            os.environ["KAIZEN_LEARNING_DIR"] = self._orig_sink

    def _run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_LEARN_PY), *args],
            capture_output=True, text=True, timeout=15,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )

    def _checkout(self, branch: str) -> None:
        subprocess.run(["git", "checkout", "-q", "-b", branch],
                        cwd=str(self.repo), check=True, capture_output=True)

    def _read_sink(self) -> list[dict]:
        log = self.sink / "log.jsonl"
        if not log.is_file():
            return []
        return [json.loads(line) for line in
                 log.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestAutoCaptureBranch(_BranchBase):
    def test_master_branch_captured(self):
        r = self._run("append",
                       "--category", "roundtrips",
                       "--problem", "p", "--solution", "s", "--pattern", "x",
                       cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = self._read_sink()[0]
        self.assertEqual(entry["branch"], "master")

    def test_feature_branch_captured(self):
        self._checkout("feat/observer-phase-2")
        r = self._run("append",
                       "--category", "anti_patterns",
                       "--problem", "p", "--solution", "s", "--pattern", "x",
                       cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = self._read_sink()[0]
        self.assertEqual(entry["branch"], "feat/observer-phase-2")

    def test_no_branch_when_outside_repo(self):
        # Run from /tmp (no git repo)
        r = self._run("append",
                       "--category", "roundtrips",
                       "--problem", "p", "--solution", "s", "--pattern", "x",
                       cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = self._read_sink()[0]
        # branch field omitted (or empty) when not detectable
        self.assertNotIn("branch", entry)


class TestExplicitBranchOverride(_BranchBase):
    def test_branch_flag_overrides_auto(self):
        # On master but explicitly tag as different branch
        r = self._run("append",
                       "--category", "roundtrips",
                       "--problem", "p", "--solution", "s", "--pattern", "x",
                       "--branch", "feat/explicit",
                       cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        entry = self._read_sink()[0]
        self.assertEqual(entry["branch"], "feat/explicit")


class TestListFilterByBranch(_BranchBase):
    def test_list_filter_by_branch(self):
        # Seed 2 entries on master, 1 on feature branch
        for i in range(2):
            self._run("append",
                       "--category", "roundtrips",
                       "--problem", f"p{i}", "--solution", "s", "--pattern", "x",
                       cwd=self.repo)
        self._checkout("feat/sample")
        self._run("append",
                   "--category", "roundtrips",
                   "--problem", "branch-p", "--solution", "s", "--pattern", "x",
                   cwd=self.repo)
        # Filter
        r = self._run("list", "--branch", "feat/sample", "--json",
                       cwd=self.repo)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["problem"], "branch-p")

        r = self._run("list", "--branch", "master", "--json", cwd=self.repo)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)


if __name__ == "__main__":
    unittest.main()
