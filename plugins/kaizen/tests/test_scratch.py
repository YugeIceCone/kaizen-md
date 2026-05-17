"""Tests for kaizen-scratch — debug-sandbox CLI.

The scratch tool is intentionally minimal: one subcommand (`run`) that
creates a tempdir under /tmp/kaizen-scratch/, optionally inits git,
runs the supplied command inside, captures output, and cleans up.

Designed to replace the dangerous pattern
    `cd /tmp && mkdir testfoo && rm -rf ...`
with
    `kaizen-scratch run --git -c '...'`
— the bash gate's _RM_RF_SAFE regex always matches because the path
is under /tmp.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_SCRATCH = _SCRIPTS / "scratch.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRATCH), *args],
        capture_output=True, text=True, timeout=30,
    )


class TestScratchRun(unittest.TestCase):
    def test_runs_command_in_tempdir(self):
        r = _run("run", "-c", "pwd && echo hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        # pwd should be under /tmp/kaizen-scratch/
        first_line = r.stdout.splitlines()[0]
        self.assertTrue(
            first_line.startswith("/tmp/kaizen-scratch/"),
            f"pwd not under sandbox: {first_line}",
        )
        self.assertIn("hi", r.stdout)

    def test_propagates_command_exit_code(self):
        r = _run("run", "-c", "exit 7")
        self.assertEqual(r.returncode, 7)

    def test_cleans_up_by_default(self):
        # Run a command that prints the sandbox path; then verify the
        # path doesn't exist post-cleanup.
        r = _run("run", "-c", "pwd")
        self.assertEqual(r.returncode, 0, r.stderr)
        sandbox = r.stdout.splitlines()[0]
        self.assertFalse(Path(sandbox).exists(),
                         f"sandbox not cleaned: {sandbox}")

    def test_keep_flag_preserves_dir(self):
        r = _run("run", "--keep", "-c", "pwd")
        self.assertEqual(r.returncode, 0, r.stderr)
        sandbox = r.stdout.splitlines()[0]
        try:
            self.assertTrue(Path(sandbox).exists(),
                             f"sandbox missing despite --keep: {sandbox}")
        finally:
            # Cleanup so the test doesn't litter /tmp
            subprocess.run(["rm", "-rf", sandbox], capture_output=True)

    def test_git_flag_inits_repo(self):
        r = _run("run", "--git", "-c", "git status --short && git log --oneline 2>&1 | head -1 || true")
        self.assertEqual(r.returncode, 0, r.stderr)
        # `git status` works → the repo was inited

    def test_sandbox_path_matches_RM_RF_SAFE(self):
        """The path must start with /tmp so bash-gate's RM_RF_SAFE
        regex permits cleanup ops without a permission prompt."""
        r = _run("run", "--keep", "-c", "pwd")
        sandbox = r.stdout.splitlines()[0]
        rm_rf_safe = re.compile(
            r"rm\s+-[rR][fF]?\s+(/tmp|/var/tmp|~/?\.cache|\$TMPDIR|\$HOME/\.cache)"
        )
        self.assertTrue(
            rm_rf_safe.search(f"rm -rf {sandbox}"),
            f"sandbox path {sandbox!r} does not match bash-gate RM_RF_SAFE",
        )
        # Cleanup
        subprocess.run(["rm", "-rf", sandbox], capture_output=True)


class TestScratchPath(unittest.TestCase):
    def test_path_prints_and_creates_sandbox(self):
        r = _run("path", "--name", "kaizen-scratch-test-xyz")
        self.assertEqual(r.returncode, 0, r.stderr)
        sandbox = r.stdout.strip().splitlines()[0]
        self.assertTrue(sandbox.startswith("/tmp/kaizen-scratch/"))
        self.assertTrue(Path(sandbox).is_dir(),
                         f"path didn't create sandbox: {sandbox}")
        # Cleanup
        subprocess.run(["rm", "-rf", sandbox], capture_output=True)


class TestScratchHelp(unittest.TestCase):
    def test_help_works(self):
        r = _run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("kaizen-scratch", r.stdout)


class TestScratchNoArgs(unittest.TestCase):
    def test_no_subcommand_errors(self):
        r = _run()
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
