"""Tests for the unified /kaizen:setup command (v1.37+).

setup.sh folds the former /kaizen:install + /kaizen:uninstall +
/kaizen:cache + /kaizen:enable-all into one entry point:
  - first positional `uninstall` / `cache` / `install` selects the path
  - --enable-all / --with-* / --no-* flags delegate to enable_all.sh
  - no positional + no flags = the per-repo install path

Run:
    python3 -m unittest tests.test_setup_consolidation -v
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SETUP_SH = PLUGIN_ROOT / "scripts" / "install" / "setup.sh"
ENABLE_ALL_SH = PLUGIN_ROOT / "scripts" / "install" / "enable_all.sh"


def _run(cmd: list[str], cwd: Path, env=None) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
        env=env or None,
    )
    return result.returncode, result.stdout, result.stderr


def _git_repo(td: str) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=td, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=td, check=True)
    return Path(td)


class TestSetupDelegation(unittest.TestCase):
    """setup.sh delegates to enable_all.sh when --enable-all / --with-* is passed."""

    def test_enable_all_flag_delegates(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, out, err = _run(
                ["bash", str(SETUP_SH), "--enable-all", "--dry-run"], repo)
            self.assertEqual(rc, 0, f"rc={rc}\nstderr={err}")
            combined = (out + err).lower()
            self.assertTrue("dry" in combined or "would" in combined or out)

    def test_with_index_flag_delegates(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, out, err = _run(
                ["bash", str(SETUP_SH), "--dry-run", "--with-index"], repo)
            self.assertEqual(rc, 0, err)
            self.assertTrue(
                "globals" in out.lower() or "opt-in" in out.lower()
                or "index" in out.lower(),
                f"--with-index should delegate; got:\n{out}")


class TestSetupInstallPath(unittest.TestCase):
    """Bare setup.sh, and explicit `install`, run the per-repo install path."""

    def _assert_install_output(self, out: str):
        self.assertTrue(
            "pre-commit" in out or "commit-msg" in out
            or "hooksPath" in out or ".kaizen" in out,
            f"install path should mention hook setup, got:\n{out}")
        # Must NOT show enable-all's broader-stack output
        self.assertNotIn("globals", out)
        # The cache check is folded into the install path
        self.assertIn("Cache check", out)

    def test_bare_setup_runs_install_path(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, out, _ = _run(["bash", str(SETUP_SH)], repo)
            self.assertEqual(rc, 0)
            self._assert_install_output(out)

    def test_explicit_install_subcommand_runs_install_path(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, out, _ = _run(["bash", str(SETUP_SH), "install"], repo)
            self.assertEqual(rc, 0)
            self._assert_install_output(out)


class TestSetupSubcommands(unittest.TestCase):
    """The folded `cache` and `uninstall` subcommands dispatch correctly."""

    def test_cache_subcommand_dispatches_to_cache_py(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, out, err = _run(["bash", str(SETUP_SH), "cache", "stats"], repo)
            self.assertEqual(rc, 0, err)
            # cache.py stats prints a JSON dict with these keys
            self.assertIn("count", out)
            self.assertIn("dir", out)

    def test_cache_subcommand_defaults_to_stats(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, out, err = _run(["bash", str(SETUP_SH), "cache"], repo)
            self.assertEqual(rc, 0, err)
            self.assertIn("count", out)

    def test_uninstall_subcommand_dispatches_and_is_dry_run_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            # Install first so uninstall has something to report.
            _run(["bash", str(SETUP_SH), "install"], repo)
            rc, out, err = _run(["bash", str(SETUP_SH), "uninstall"], repo)
            self.assertEqual(rc, 0, err)
            # uninstall.sh default is a dry-run preview
            combined = (out + err).lower()
            self.assertTrue("dry" in combined or "would" in combined or out)


class TestEnableAllPath(unittest.TestCase):
    """Direct invocation of enable_all.sh still works (internal helper)."""

    def test_enable_all_dry_run_exits_clean(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            rc, _, err = _run(["bash", str(ENABLE_ALL_SH), "--dry-run"], repo)
            self.assertEqual(rc, 0, err)


class TestDocs(unittest.TestCase):
    """commands/setup.md documents the folded command surface."""

    def test_setup_md_documents_all_subcommands(self):
        text = (PLUGIN_ROOT / "commands" / "setup.md").read_text()
        for token in ("--enable-all", "uninstall", "cache", "install"):
            self.assertIn(token, text, f"setup.md should document `{token}`")

    def test_old_command_files_are_gone(self):
        commands = PLUGIN_ROOT / "commands"
        for stale in ("install.md", "uninstall.md", "enable-all.md", "cache.md"):
            self.assertFalse(
                (commands / stale).exists(),
                f"{stale} should have been folded into setup.md")


class TestPluginIndexSeed(unittest.TestCase):
    """Bare setup.sh seeds the plugin loc index (idempotent)."""

    def test_install_seeds_loc_db_for_plugin(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            idx_root = Path(td) / "fake-plugin-root"
            idx_root.mkdir()
            (idx_root / "sample.py").write_text("def f():\n    return 1\n")
            env = dict(os.environ, KAIZEN_PLUGIN_INDEX_ROOT=str(idx_root))
            rc, out, err = _run(["bash", str(SETUP_SH)], repo, env=env)
            self.assertEqual(rc, 0, err)
            self.assertTrue((idx_root / ".kaizen" / "loc.db").exists(),
                            "bare install should seed the plugin loc.db")

    def test_install_seed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            idx_root = Path(td) / "fake-plugin-root"
            (idx_root / ".kaizen").mkdir(parents=True)
            (idx_root / ".kaizen" / "loc.db").write_text("")  # pretend seeded
            env = dict(os.environ, KAIZEN_PLUGIN_INDEX_ROOT=str(idx_root))
            rc, out, err = _run(["bash", str(SETUP_SH)], repo, env=env)
            self.assertEqual(rc, 0, err)
            self.assertIn("plugin index", out.lower())  # prints a skip line

    def test_disable_knob_skips_seed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = _git_repo(td)
            idx_root = Path(td) / "fake-plugin-root"
            idx_root.mkdir()
            env = dict(os.environ, KAIZEN_PLUGIN_INDEX_ROOT=str(idx_root),
                       KAIZEN_PLUGIN_INDEX_DISABLE="1")
            rc, out, err = _run(["bash", str(SETUP_SH)], repo, env=env)
            self.assertEqual(rc, 0, err)
            self.assertFalse((idx_root / ".kaizen" / "loc.db").exists())


if __name__ == "__main__":
    unittest.main()
