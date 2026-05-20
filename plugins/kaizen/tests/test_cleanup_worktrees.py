"""Phase 5.A: kaizen-cleanup-worktrees finds + removes merged worktrees.

Uses an actual git tempdir + worktrees so the subprocess calls run
against real git. No mocking the git surface — keeps the integration
honest.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=10, check=False,
    )

class TestDetectDefaultBranch(unittest.TestCase):

    def test_env_override_wins(self):
        import cleanup_worktrees as cw
        from unittest.mock import patch
        with patch.dict(os.environ,
                        {"KAIZEN_DEFAULT_BRANCH": "develop"}):
            self.assertEqual(cw.detect_default_branch(), "develop")

    def test_fallback_to_main_or_master(self):
        import cleanup_worktrees as cw
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            _git(cwd, "init", "-q", "-b", "main")
            (cwd / "f.txt").write_text("hi")
            _git(cwd, "add", ".")
            _git(cwd, "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "-m", "init")
            from unittest.mock import patch
            env = {k: v for k, v in os.environ.items()
                   if k != "KAIZEN_DEFAULT_BRANCH"}
            with patch.dict(os.environ, env, clear=True):
                cwd_save = os.getcwd()
                os.chdir(cwd)
                try:
                    self.assertEqual(cw.detect_default_branch(cwd=cwd), "main")
                finally:
                    os.chdir(cwd_save)

class TestFindRemovable(unittest.TestCase):

    def _init_repo(self, td: Path) -> Path:
        _git(td, "init", "-q", "-b", "main")
        (td / "f.txt").write_text("hi")
        _git(td, "add", ".")
        _git(td, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "init")
        return td

    def test_no_worktrees_returns_empty(self):
        import cleanup_worktrees as cw
        with tempfile.TemporaryDirectory() as td:
            cwd = self._init_repo(Path(td))
            cwd_save = os.getcwd()
            os.chdir(cwd)
            try:
                from unittest.mock import patch
                with patch.dict(os.environ,
                                {"KAIZEN_DEFAULT_BRANCH": "main"}):
                    self.assertEqual(cw.find_removable(cwd=cwd), [])
            finally:
                os.chdir(cwd_save)

    def test_merged_worktree_listed_unmerged_excluded(self):
        import cleanup_worktrees as cw
        # Two sibling tempdirs: one for the main repo, one for worktrees.
        # Putting wt_root in a SEPARATE TemporaryDirectory keeps each
        # parallel test worker's worktrees on isolated paths (avoids
        # races over a shared /tmp/wt-test-root).
        with tempfile.TemporaryDirectory() as td_repo, \
             tempfile.TemporaryDirectory() as td_wts:
            cwd = self._init_repo(Path(td_repo))
            wt_root = Path(td_wts)
            # Worktree 1: branch that gets merged
            wt_merged = wt_root / "merged"
            r = _git(cwd, "worktree", "add", "-b", "feat-done",
                     str(wt_merged))
            if r.returncode != 0 or not wt_merged.is_dir():
                self.skipTest(
                    f"git worktree add failed in this env: "
                    f"rc={r.returncode} stderr={r.stderr[:200]}")
            (wt_merged / "f.txt").write_text("a")
            _git(wt_merged, "add", ".")
            _git(wt_merged, "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "-m", "feat done")
            _git(cwd, "-c", "user.email=t@t", "-c", "user.name=t",
                 "merge", "-q", "feat-done")
            # Worktree 2: branch that stays unmerged
            wt_unmerged = wt_root / "unmerged"
            _git(cwd, "worktree", "add", "-q", "-b", "feat-wip",
                 str(wt_unmerged))
            (wt_unmerged / "g.txt").write_text("b")
            _git(wt_unmerged, "add", ".")
            _git(wt_unmerged, "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "-m", "wip")

            from unittest.mock import patch
            with patch.dict(os.environ,
                            {"KAIZEN_DEFAULT_BRANCH": "main"}):
                removable = cw.find_removable(cwd=cwd)
            branches = {r["branch"] for r in removable}
            self.assertIn("feat-done", branches)
            self.assertNotIn("feat-wip", branches)
            # Cleanup the worktrees so the parent tempdir cleanup works
            _git(cwd, "worktree", "remove", "--force", str(wt_merged))
            _git(cwd, "worktree", "remove", "--force", str(wt_unmerged))

class TestMainCLI(unittest.TestCase):

    def test_default_is_dry_run(self):
        import cleanup_worktrees as cw
        from unittest.mock import patch
        with patch.object(cw, "find_removable", return_value=[]):
            # Returns 0; doesn't call remove_worktree (no candidates)
            self.assertEqual(cw.main([]), 0)

    def test_apply_flag_calls_remove(self):
        import cleanup_worktrees as cw
        from unittest.mock import patch
        candidates = [{"path": "/fake/wt", "branch": "feat-x",
                       "locked": False, "prunable": False, "head": "abc"}]
        with patch.object(cw, "find_removable", return_value=candidates), \
             patch.object(cw, "remove_worktree",
                          return_value=(True, "removed /fake/wt")) as rm:
            self.assertEqual(cw.main(["--apply"]), 0)
            rm.assert_called_once_with("/fake/wt")

if __name__ == "__main__":
    unittest.main()
