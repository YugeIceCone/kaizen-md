"""Regression test for prune_bin_symlinks.py — GC of dangling kaizen-* symlinks.

`/kaizen:setup` symlinks every `<plugin>/bin/kaizen-*` into `~/.local/bin/`.
When a source bin gets renamed or deleted, the user-bin symlink is left
dangling — 16 such orphans were found on 2026-05-18 from prior plugin
versions. setup.sh now runs this GC before re-linking to keep the
user-bin clean.

Run:
    python3 -m unittest tests.test_prune_bin_symlinks -v
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "util" / "_prune_bin_symlinks.py"
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


class TestPruneBinSymlinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.user_bin = Path(self.tmp.name) / "bin"
        self.user_bin.mkdir()
        self.real_target = Path(self.tmp.name) / "real-target"
        self.real_target.touch()
        self.missing_target = Path(self.tmp.name) / "missing-target"

    def tearDown(self):
        self.tmp.cleanup()

    def _link(self, name: str, target: Path) -> Path:
        link = self.user_bin / name
        link.symlink_to(target)
        return link

    def test_removes_dangling_kaizen_symlink(self):
        self._link("kaizen-dead", self.missing_target)
        result = _run("--user-bin", str(self.user_bin))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(
            os.path.lexists(self.user_bin / "kaizen-dead"),
            "dangling kaizen-* symlink must be removed",
        )

    def test_keeps_live_kaizen_symlink(self):
        self._link("kaizen-alive", self.real_target)
        result = _run("--user-bin", str(self.user_bin))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(
            os.path.lexists(self.user_bin / "kaizen-alive"),
            "live kaizen-* symlink must be preserved",
        )

    def test_ignores_non_kaizen_symlinks(self):
        self._link("other-dead", self.missing_target)
        result = _run("--user-bin", str(self.user_bin))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(
            os.path.lexists(self.user_bin / "other-dead"),
            "non-kaizen symlinks must not be touched even when dangling",
        )

    def test_ignores_real_files(self):
        (self.user_bin / "kaizen-user-script").write_text("#!/bin/sh\necho hi\n")
        result = _run("--user-bin", str(self.user_bin))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(
            (self.user_bin / "kaizen-user-script").exists(),
            "non-symlink kaizen-* files (user-created) must be preserved",
        )

    def test_dry_run_does_not_remove(self):
        self._link("kaizen-dead", self.missing_target)
        result = _run("--user-bin", str(self.user_bin), "--dry-run")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(
            os.path.lexists(self.user_bin / "kaizen-dead"),
            "--dry-run must report but not remove",
        )

    def test_json_output_lists_removed(self):
        self._link("kaizen-a", self.missing_target)
        self._link("kaizen-b", self.real_target)
        result = _run("--user-bin", str(self.user_bin), "--json")
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(["kaizen-a"], payload["removed"])
        self.assertEqual(1, payload["count"])
        self.assertFalse(payload["dry_run"])

    def test_missing_user_bin_is_noop(self):
        result = _run("--user-bin", str(Path(self.tmp.name) / "nope"))
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
