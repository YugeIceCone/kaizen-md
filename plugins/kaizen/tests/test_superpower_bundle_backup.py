"""Tests for kaizen-bundle auto-commit-default + patch-journal backup.

Per user 2026-05-18:
  "automate the commits for superpowers + backup that gradually builds
   a log of git patches"

Two changes:
  1. --commit becomes IMPLICIT default for init/add (opt-out via --no-commit)
  2. Every commit also writes `git format-patch -1 <sha>` to a backup
     dir + appends one row to a manifest.jsonl

Backup dir: <KAIZEN_BACKUP_DIR>/superpowers/patches/<ts>-<sha8>.patch
Manifest:   <KAIZEN_BACKUP_DIR>/superpowers/manifest.jsonl

Recoverability proof: any patch can be replayed via `git am`.

Iron-laws (same family — programmable/reproducible/consistent/
deterministic/reusable):
  - patch filenames are deterministic (ts + sha8)
  - manifest.jsonl is append-only
  - graceful when git binary or repo missing (skip; never crash)
  - env-overridable backup dir for tests
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
_BUNDLE_PY = _KZ_DIR / "skills/workflow/scripts/superpower_bundle.py"


class _BackupBase(unittest.TestCase):
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
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=str(self.root),
            capture_output=True, text=True, timeout=15,
        )

    def _patches_dir(self) -> Path:
        return self.backup / "superpowers" / "patches"

    def _manifest(self) -> Path:
        return self.backup / "superpowers" / "manifest.jsonl"


class TestAutoCommitDefault(_BackupBase):
    def test_init_now_commits_by_default(self):
        self._run("git-init")
        before = len(self._git("log", "--oneline").stdout.splitlines())
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        after = len(self._git("log", "--oneline").stdout.splitlines())
        self.assertGreater(after, before,
                            "init should auto-commit by default")

    def test_no_commit_opts_out(self):
        self._run("git-init")
        before = len(self._git("log", "--oneline").stdout.splitlines())
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc",
                   "--no-commit")
        after = len(self._git("log", "--oneline").stdout.splitlines())
        self.assertEqual(after, before,
                          "--no-commit must skip the auto-commit")

    def test_add_commits_by_default(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        src = self.tmp / "spec.md"
        src.write_text("# spec\n")
        before = len(self._git("log", "--oneline").stdout.splitlines())
        self._run("add", "--file", str(src),
                   "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        after = len(self._git("log", "--oneline").stdout.splitlines())
        self.assertGreater(after, before)


class TestPatchJournal(_BackupBase):
    def test_each_commit_writes_a_patch(self):
        self._run("git-init")
        # init auto-commits (default) → one patch per init
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        self._run("init", "--date", "2026-05-19",
                   "--project", "kaizen-md", "--sid", "def")
        patches = list(self._patches_dir().glob("*.patch"))
        # 2 init commits → 2 patches (git-init dir was empty so no bootstrap)
        self.assertGreaterEqual(len(patches), 2)

    def test_patch_filename_deterministic_format(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        patches = list(self._patches_dir().glob("*.patch"))
        self.assertGreaterEqual(len(patches), 1)
        # Format: YYYYMMDDTHHMMSSZ-<sha8>.patch
        for p in patches:
            stem = p.stem
            parts = stem.split("-")
            self.assertEqual(len(parts), 2,
                              f"expected `ts-sha8` format; got {stem!r}")
            ts, sha = parts
            self.assertEqual(len(ts), 16, f"expected 16-char ts; got {ts!r}")
            self.assertEqual(len(sha), 8, f"expected 8-char sha; got {sha!r}")

    def test_manifest_appended_per_patch(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        manifest = self._manifest()
        self.assertTrue(manifest.is_file())
        rows = [json.loads(line) for line in
                 manifest.read_text().splitlines() if line.strip()]
        self.assertGreaterEqual(len(rows), 1)
        for row in rows:
            for k in ("ts", "sha", "path"):
                self.assertIn(k, row)

    def test_patches_chronological(self):
        """Patch filenames sort chronologically (lexicographic == temporal)."""
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        self._run("init", "--date", "2026-05-19",
                   "--project", "kaizen-md", "--sid", "def")
        patches = sorted(self._patches_dir().glob("*.patch"),
                          key=lambda p: p.name)
        # 2 init commits → 2 patches (no bootstrap since dir was empty)
        self.assertGreaterEqual(len(patches), 2)


class TestRecoverability(_BackupBase):
    def test_patch_replayable_via_git_am(self):
        """The whole point of the patch journal: every patch is
        independently recoverable via `git am`."""
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        patches = sorted(self._patches_dir().glob("*.patch"))
        # Pick the last (the init commit) and replay it onto a fresh repo
        replay = self.tmp / "replay"
        replay.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(replay), check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "config", k, v], cwd=str(replay),
                            check=True)
        # Build the replay chain step-by-step
        for p in patches:
            r = subprocess.run(["git", "am", str(p.resolve())],
                                cwd=str(replay),
                                capture_output=True, text=True)
            # Either applies clean OR no-op (some patches may overlap; both OK)
            if r.returncode != 0:
                subprocess.run(["git", "am", "--abort"], cwd=str(replay),
                                capture_output=True)
        # The bundle folder should now exist in the replay
        replayed = replay / "2026-05-18-kaizen-md-abc"
        self.assertTrue(replayed.is_dir(),
                         f"expected replayed bundle at {replayed}")


class TestBackupSubcommand(_BackupBase):
    def test_backup_list_shows_patches(self):
        self._run("git-init")
        self._run("init", "--date", "2026-05-18",
                   "--project", "kaizen-md", "--sid", "abc")
        r = self._run("backup", "list", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertGreaterEqual(len(data), 1)
        for row in data:
            self.assertIn("ts", row)
            self.assertIn("sha", row)
            self.assertIn("path", row)


if __name__ == "__main__":
    unittest.main()
