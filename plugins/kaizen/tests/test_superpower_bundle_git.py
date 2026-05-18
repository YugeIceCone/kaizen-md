"""Tests for kaizen-bundle git automation.

Per user 2026-05-18 direction: superpowers/ becomes its own git repo,
and bundle operations auto-commit. Same code rules apply (TDD / KISS /
DRY / programmable / reproducible / consistent / deterministic / reusable).

New subcommand + flag:
  kaizen-bundle git-init    — `git init` in the superpowers root (idempotent)
  kaizen-bundle init / add  — auto-commit by default; opt-out via --no-commit
                              (the original --commit opt-in flag was retired
                              in 6a717e1; default flipped per user direction)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_BUNDLE_PY = _KZ_DIR / "skills/workflow/scripts/superpower_bundle.py"


class _GitBundleBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "superpowers"
        self.root.mkdir()
        # Sandbox BOTH the superpowers dir AND the backup dir to prevent
        # patch-journal pollution of the real ~/.claude/.kaizen/backups/.
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        self._orig_backup = os.environ.get("KAIZEN_BACKUP_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)
        os.environ["KAIZEN_BACKUP_DIR"] = str(self.tmp / "backup")
        # Local git identity
        self._orig_email = os.environ.get("GIT_AUTHOR_EMAIL")
        self._orig_name = os.environ.get("GIT_AUTHOR_NAME")
        os.environ.setdefault("GIT_AUTHOR_EMAIL", "t@t")
        os.environ.setdefault("GIT_AUTHOR_NAME", "test")
        os.environ.setdefault("GIT_COMMITTER_EMAIL", "t@t")
        os.environ.setdefault("GIT_COMMITTER_NAME", "test")

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_SUPERPOWERS_DIR", self._orig),
                           ("KAIZEN_BACKUP_DIR", self._orig_backup),
                           ("GIT_AUTHOR_EMAIL", self._orig_email),
                           ("GIT_AUTHOR_NAME", self._orig_name)):
            if orig is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_BUNDLE_PY), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=str(self.root),
            capture_output=True, text=True, timeout=15,
        )

    def _is_git_repo(self) -> bool:
        return (self.root / ".git").is_dir()


class TestGitInit(_GitBundleBase):
    def test_creates_git_repo_in_superpowers_root(self):
        assert not self._is_git_repo()
        r = self._run("git-init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._is_git_repo())

    def test_idempotent_on_rerun(self):
        for _ in range(3):
            r = self._run("git-init")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._is_git_repo())

    def test_initial_commit_with_readme(self):
        """After git-init, the root README.md (if present) gets staged
        as the first commit via a single bootstrap operation."""
        (self.root / "README.md").write_text("# superpowers\n")
        self._run("git-init")
        r = self._git("log", "--oneline")
        # First commit should exist
        self.assertNotEqual(r.stdout.strip(), "",
                              "expected at least one commit after git-init")


class TestInitWithAutoCommit(_GitBundleBase):
    """Auto-commit is now DEFAULT (per user 2026-05-18 'automate the commits')."""

    def test_init_commits_by_default(self):
        self._run("git-init")
        r = self._run("init", "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self._git("log", "--oneline")
        self.assertIn("2026-05-18-kaizen-md-abc", log.stdout)

    def test_no_commit_flag_skips(self):
        self._run("git-init")
        before = len(self._git("log", "--oneline").stdout.splitlines())
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc",
                   "--no-commit")
        after = len(self._git("log", "--oneline").stdout.splitlines())
        self.assertEqual(after, before,
                          "--no-commit must skip the auto-commit")


class TestAddWithAutoCommit(_GitBundleBase):
    def test_add_commit_creates_commit_referencing_filename(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        src = self.tmp / "spec.md"
        src.write_text("# spec\n")
        r = self._run("add", "--file", str(src),
                       "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self._git("log", "--oneline")
        self.assertIn("spec.md", log.stdout)


class TestGitInitGracefulWhenGitMissing(_GitBundleBase):
    def test_handles_missing_git_binary_gracefully(self, monkeypatch=None):
        # Simulate `git` not on PATH
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            r = self._run("git-init")
            # Should NOT crash; exit 1 with a helpful message
            self.assertEqual(r.returncode, 1)
            self.assertIn("git", (r.stderr + r.stdout).lower())
        finally:
            os.environ["PATH"] = old_path


class TestCommitDeterministic(_GitBundleBase):
    """Reproducibility — given same inputs, the commit-message subject is identical."""

    def test_subject_format_includes_bundle_name(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        log = self._git("log", "-1", "--format=%s")
        subject = log.stdout.strip()
        # Should be a deterministic, parseable format
        self.assertIn("bundle(2026-05-18-kaizen-md-abc)", subject)


if __name__ == "__main__":
    unittest.main()
