"""Tests for precompact-snapshot.sh — BK-014: systemMessage must be
honest (snapshot really completed, message reflects actual path).

Old behavior: hook backgrounded backup.sh (`&`) and unconditionally
printed 'snapshotted to ~/.claude/backups/kaizen/' — but:
  (a) tarball didn't exist yet when message fired (backgrounded);
  (b) path string was wrong (real location is ~/.claude/.kaizen/backups/<slug>/).

New behavior: backup runs synchronously (~200ms for 25M); message
reports the actual tarball path only if backup succeeded; on failure
the systemMessage is omitted (hook still exits 0 — never blocks).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/precompact-snapshot.sh"


class PrecompactHookBase(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.backup_dir = self.tmp / "backups"
        self.backup_dir.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        # Need a commit so `git rev-parse --show-toplevel` works
        (self.repo / ".kaizen.toml").write_text("[gate]\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "init"],
            cwd=self.repo, check=True,
        )

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()

    def _fire(self, stdin: str = "{}") -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["KAIZEN_BACKUP_DIR"] = str(self.backup_dir)
        # Run from inside the fake repo so `git rev-parse` finds it
        return subprocess.run(
            ["bash", str(_HOOK)],
            input=stdin, capture_output=True, text=True,
            timeout=10, env=env, cwd=str(self.repo),
        )


class TestHonestSystemMessage(PrecompactHookBase):
    def test_message_only_claims_snapshot_after_tarball_exists(self):
        r = self._fire('{"session_id": "test-sid"}')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout or "{}")
        msg = out.get("systemMessage", "")
        if "snapshot" in msg.lower():
            # Claim of snapshot → at least one tarball must exist on disk
            repo_slug = str(self.repo.resolve()).replace("/", "-").lstrip("-")
            slug_dir = self.backup_dir / repo_slug
            tarballs = list(slug_dir.glob("*.tar.gz")) if slug_dir.is_dir() else []
            self.assertGreater(
                len(tarballs), 0,
                f"systemMessage claimed snapshot but no tarball at {slug_dir}",
            )

    def test_message_references_actual_backup_path(self):
        r = self._fire('{"session_id": "test-sid"}')
        out = json.loads(r.stdout or "{}")
        msg = out.get("systemMessage", "")
        if msg:
            # Must NOT contain the old wrong path
            self.assertNotIn(
                "~/.claude/backups/kaizen", msg,
                "old (wrong) backup path still in message; should be ~/.claude/.kaizen/backups/<slug>/",
            )


class TestNeverBlocksHostFlow(PrecompactHookBase):
    def test_exits_zero_even_when_no_state_to_snapshot(self):
        # Repo without .kaizen.toml → no snapshot, but hook must still
        # exit 0 with valid JSON (compaction proceeds)
        (self.repo / ".kaizen.toml").unlink()
        r = self._fire()
        self.assertEqual(r.returncode, 0)
        # Stdout must be valid JSON
        json.loads(r.stdout or "{}")


if __name__ == "__main__":
    unittest.main()
