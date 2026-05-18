"""Tests for kaizen-bundle git automation.

Per user 2026-05-18 direction: superpowers/ becomes its own git repo,
and bundle operations auto-commit. Same code rules apply (TDD / KISS /
DRY / programmable / reproducible / consistent / deterministic / reusable).

New subcommand + flag:
  kaizen-bundle git-init    — `git init` in the superpowers root (idempotent)
  kaizen-bundle init --commit / add --commit
                            — auto-commit via the local git after the operation
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
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)
        # Local git identity (tests run in arbitrary env)
        self._orig_email = os.environ.get("GIT_AUTHOR_EMAIL")
        self._orig_name = os.environ.get("GIT_AUTHOR_NAME")
        os.environ.setdefault("GIT_AUTHOR_EMAIL", "t@t")
        os.environ.setdefault("GIT_AUTHOR_NAME", "test")
        os.environ.setdefault("GIT_COMMITTER_EMAIL", "t@t")
        os.environ.setdefault("GIT_COMMITTER_NAME", "test")

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_SUPERPOWERS_DIR", self._orig),
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
    def test_init_commit_flag_creates_per_bundle_commit(self):
        self._run("git-init")
        r = self._run("init", "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc",
                       "--commit")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self._git("log", "--oneline")
        # Expect the bundle-init commit subject to mention the bundle name
        self.assertIn("2026-05-18-kaizen-md-abc", log.stdout)

    def test_init_without_commit_does_not_create_commit(self):
        self._run("git-init")
        # Take baseline log count
        before = len(self._git("log", "--oneline").stdout.splitlines())
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        after = len(self._git("log", "--oneline").stdout.splitlines())
        self.assertEqual(after, before,
                          "init without --commit must not add commits")


class TestAddWithAutoCommit(_GitBundleBase):
    def test_add_commit_creates_commit_referencing_filename(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc", "--commit")
        # Loose file in tempdir
        src = self.tmp / "spec.md"
        src.write_text("# spec\n")
        r = self._run("add", "--file", str(src),
                       "--date", "2026-05-18",
                       "--project", "kaizen-md", "--sid", "abc",
                       "--commit")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self._git("log", "--oneline")
        # Commit should mention the file name
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
                   "--project", "kaizen-md", "--sid", "abc", "--commit")
        log = self._git("log", "-1", "--format=%s")
        subject = log.stdout.strip()
        # Should be a deterministic, parseable format
        self.assertIn("bundle(2026-05-18-kaizen-md-abc)", subject)


if __name__ == "__main__":
    unittest.main()
