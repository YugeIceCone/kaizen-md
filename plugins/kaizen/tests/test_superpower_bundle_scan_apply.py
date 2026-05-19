"""Tests for kaizen-bundle scan --apply [--branch <name>].

Closes the user 2026-05-18 directive — "create a branch for bundling
use correct metadata and dupe checks." Apply path:
  1. Skip dupes (already-in-bundle by content sha)
  2. (optional) git checkout -b <branch> in the nested superpowers repo
  3. Move each non-dupe orphan into its target bundle
     (target = <suggested_date>-<project>-? — default project=kaizen-md)
  4. Auto-commit in nested repo (kaizen-bundle's standard auto-commit)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_BUNDLE_PY = _KZ_DIR / "scripts/util/superpower_bundle.py"


class _ApplyBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "superpowers"
        self.root.mkdir()
        self.backup = self.tmp / "backup"
        self.backup.mkdir()
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        self._orig_bk = os.environ.get("KAIZEN_BACKUP_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)
        os.environ["KAIZEN_BACKUP_DIR"] = str(self.backup)
        for k, v in (("GIT_AUTHOR_EMAIL", "t@t"), ("GIT_AUTHOR_NAME", "t"),
                      ("GIT_COMMITTER_EMAIL", "t@t"),
                      ("GIT_COMMITTER_NAME", "t")):
            os.environ.setdefault(k, v)

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_SUPERPOWERS_DIR", self._orig),
                           ("KAIZEN_BACKUP_DIR", self._orig_bk)):
            if orig is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_BUNDLE_PY), *args],
            capture_output=True, text=True, timeout=20,
            env=os.environ.copy(),
        )

    def _git_branch(self) -> str:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(self.root), capture_output=True, text=True)
        return r.stdout.strip()


class TestApplyMovesOrphans(_ApplyBase):
    def test_orphan_with_date_prefix_lands_in_target_bundle(self):
        (self.root / "2026-05-17-something.md").write_text("# x\n")
        self._run("git-init")
        r = self._run("scan", "--apply", "--project", "kaizen-md")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Orphan removed
        self.assertFalse((self.root / "2026-05-17-something.md").exists())
        # File landed in 2026-05-17-kaizen-md/ bundle
        target = self.root / "2026-05-17-kaizen-md" / "2026-05-17-something.md"
        self.assertTrue(target.is_file(), f"orphan not at {target}")

    def test_no_orphans_apply_is_no_op(self):
        self._run("git-init")
        r = self._run("scan", "--apply")
        self.assertEqual(r.returncode, 0)


class TestApplySkipsDupes(_ApplyBase):
    def test_dupe_orphan_not_moved(self):
        # Existing bundle with content
        bundle = self.root / "2026-05-17-kaizen-md"
        bundle.mkdir()
        (bundle / "spec.md").write_text("# dup\n")
        # Orphan with identical content
        (self.root / "loose.md").write_text("# dup\n")
        self._run("git-init")
        r = self._run("scan", "--apply", "--project", "kaizen-md")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Orphan stays where it is (skipped because dupe)
        self.assertTrue((self.root / "loose.md").is_file(),
                         "dupe orphan should NOT be moved")


class TestApplyBranch(_ApplyBase):
    def test_branch_flag_creates_and_switches(self):
        (self.root / "2026-05-17-something.md").write_text("# x\n")
        self._run("git-init")
        # Start on master
        self.assertEqual(self._git_branch(), "master")
        r = self._run("scan", "--apply",
                       "--project", "kaizen-md",
                       "--branch", "bundle/2026-05-18-scan")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Now on the new branch
        self.assertEqual(self._git_branch(), "bundle/2026-05-18-scan")

    def test_no_branch_stays_on_current(self):
        (self.root / "2026-05-17-something.md").write_text("# x\n")
        self._run("git-init")
        r = self._run("scan", "--apply", "--project", "kaizen-md")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Still on master (no branch switch)
        self.assertEqual(self._git_branch(), "master")


if __name__ == "__main__":
    unittest.main()
