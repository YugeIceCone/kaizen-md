"""Tests for the install + enable-all consolidation (v1.33+).

`/kaizen:install --enable-all` delegates to enable_all.sh. The legacy
`/kaizen:enable-all` path still works (calls the same script). Both
entry points should produce identical dry-run output for matching args.

Run:
    python3 -m unittest tests.test_install_enable_all_consolidation -v
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "install.sh"
ENABLE_ALL_SH = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "enable_all.sh"


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


class TestInstallScriptDelegation(unittest.TestCase):
    """install.sh should hand off to enable_all.sh when --enable-all is passed."""

    def test_install_help_with_enable_all_flag_does_not_error_immediately(self):
        """The delegation path triggers on --enable-all; --dry-run keeps
        the call cheap. Just verify the script doesn't bomb."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=True)
            rc, out, err = _run(
                ["bash", str(INSTALL_SH), "--enable-all", "--dry-run"],
                Path(td),
            )
            # enable_all.sh with --dry-run exits 0 and prints what would run
            self.assertEqual(rc, 0, f"rc={rc}\nstderr={err}")
            # Dry-run marker from enable_all.sh's color codes / steps
            combined = out + err
            self.assertTrue(
                "dry" in combined.lower() or "would" in combined.lower()
                or len(out) > 0,
                f"expected dry-run output, got:\n{combined}",
            )

    def test_install_without_flags_runs_standard_install_path(self):
        """Bare install.sh — no --enable-all — should NOT delegate."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=True)
            # Use git config so we don't conflict with user's global
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=td, check=True,
            )
            rc, out, _ = _run(
                ["bash", str(INSTALL_SH)],
                Path(td),
            )
            self.assertEqual(rc, 0)
            # The bare-install path writes about pre-commit / commit-msg hooks
            self.assertTrue(
                "pre-commit" in out or "commit-msg" in out
                or "hooksPath" in out
                or ".kaizen" in out,
                f"bare install should mention hook setup, got:\n{out}",
            )
            # Should NOT include enable-all's broader-stack output
            self.assertNotIn("globals", out)

    def test_install_with_with_index_also_delegates(self):
        """Any --with-* flag should delegate to enable_all.sh too."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=True)
            rc, out, err = _run(
                ["bash", str(INSTALL_SH), "--dry-run", "--with-index"],
                Path(td),
            )
            self.assertEqual(rc, 0, err)
            # Delegated → output mentions the broader stack
            self.assertTrue(
                "globals" in out.lower() or "opt-in" in out.lower()
                or "index" in out.lower(),
                f"--with-index should trigger delegation; got:\n{out}",
            )


class TestEnableAllPath(unittest.TestCase):
    """Direct invocation of enable_all.sh still works."""

    def test_enable_all_dry_run_exits_clean(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=True)
            rc, out, err = _run(
                ["bash", str(ENABLE_ALL_SH), "--dry-run"],
                Path(td),
            )
            self.assertEqual(rc, 0, err)


class TestDocs(unittest.TestCase):
    """The two command docs reflect the consolidation."""

    def test_install_md_documents_enable_all(self):
        text = (PLUGIN_ROOT / "commands" / "install.md").read_text()
        self.assertIn("--enable-all", text)
        self.assertIn("enable_all.sh", text)

    def test_enable_all_md_notes_consolidation(self):
        text = (PLUGIN_ROOT / "commands" / "enable-all.md").read_text()
        self.assertIn("/kaizen:install --enable-all", text)


if __name__ == "__main__":
    unittest.main()
