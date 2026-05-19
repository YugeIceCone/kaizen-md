"""Phase C: capture --tier project must use git-root slug (not cwd slug).

This aligns brain capture with kaizen-better-memory: both compute the
project slug from the git repo root, so all captures (manual + Claude
Code auto-memory) land in the same dir + are indexed by the same
MEMORY.md.

Pre-fix bug: capture from `~/repo/sub/dir/` wrote to
``~/.claude/projects/-home-x-repo-sub-dir/memory/`` while auto-memory
wrote to ``~/.claude/projects/-home-x-repo/memory/`` — split-brain.

Sandbox via KAIZEN_BETTER_MEMORY_DIR (env override wins over git probe).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "brain"))


class TestProjectMemoryRootResolution(unittest.TestCase):
    """`_brain.project_memory_root()` must compose the same git-root
    convention used by better_memory._default_memory_dir."""

    def test_returns_git_root_slug_when_in_subdir(self):
        import _brain
        fake_repo = "/fake/repo/root"

        def fake_run(*args, **kw):
            class R:
                returncode = 0
                stdout = fake_repo + "\n"
                stderr = ""
            return R()

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(_brain.Path, "home",
                          return_value=Path("/fake/home")):
            d = _brain.project_memory_root()

        # Slug derived from git root, not cwd
        self.assertIn(fake_repo.replace("/", "-"), str(d))
        self.assertTrue(str(d).endswith("/memory"))

    def test_falls_back_to_cwd_outside_git_repo(self):
        import _brain

        def fake_run(*args, **kw):
            class R:
                returncode = 128
                stdout = ""
                stderr = "fatal: not a git repository"
            return R()

        fake_cwd = Path("/fake/cwd/outside-git")
        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(_brain.Path, "cwd", return_value=fake_cwd), \
             patch.object(_brain.Path, "home",
                          return_value=Path("/fake/home")):
            d = _brain.project_memory_root()

        self.assertIn(str(fake_cwd).replace("/", "-"), str(d))

    def test_explicit_cwd_arg_preserves_existing_signature(self):
        """Don't break callers passing an explicit cwd. Explicit cwd still
        resolves via git root (rooted at that cwd) when possible."""
        import _brain

        def fake_run(*args, **kw):
            cwd_arg = kw.get("cwd") or "/fallback"
            class R:
                returncode = 0
                stdout = str(cwd_arg) + "\n"
                stderr = ""
            return R()

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(_brain.Path, "home",
                          return_value=Path("/fake/home")):
            d = _brain.project_memory_root(cwd=Path("/some/where"))

        # Should have probed git from /some/where
        self.assertIn("some-where", str(d))


class TestBetterMemoryAlignment(unittest.TestCase):
    """Brain capture (--tier project) and kaizen-better-memory regen
    must resolve to the same dir for the same repo."""

    def test_both_resolve_to_same_dir_when_in_repo(self):
        import _brain
        import better_memory

        def fake_run(*args, **kw):
            class R:
                returncode = 0
                stdout = "/fake/repo\n"
                stderr = ""
            return R()

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(_brain.Path, "home",
                          return_value=Path("/fake/home")), \
             patch.object(better_memory.Path, "home",
                          return_value=Path("/fake/home")):
            brain_dir = _brain.project_memory_root()
            mem_dir = better_memory._default_memory_dir()

        self.assertEqual(str(brain_dir), str(mem_dir),
            "brain and better_memory must agree on the project memory dir")


if __name__ == "__main__":
    unittest.main()
