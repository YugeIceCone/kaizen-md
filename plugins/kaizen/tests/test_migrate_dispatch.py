"""Tests for migrate.py — Tier-2 consolidated data-migrator dispatcher.

Covers the kaizen-migrate <path|legacy> verb dispatch. Uses subprocess
calls (the dispatcher uses os.execvp so in-process testing would
replace the test runner). Each underlying script is invoked with a
no-op flag (--help / status) so the test is hermetic and fast.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_MIGRATE = _SCRIPTS / "migrate.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    """Invoke migrate.py with the given args via python3 subprocess."""
    return subprocess.run(
        [sys.executable, str(_MIGRATE), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestUsage(unittest.TestCase):
    def test_no_args_prints_usage_and_exits_2(self):
        result = _run()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: kaizen-migrate", result.stdout)
        self.assertIn("path", result.stdout)
        self.assertIn("legacy", result.stdout)

    def test_help_flag_prints_usage_and_exits_0(self):
        result = _run("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: kaizen-migrate", result.stdout)

    def test_short_help_flag_also_works(self):
        result = _run("-h")
        self.assertEqual(result.returncode, 0)

    def test_usage_mentions_brain_migrate_pointer(self):
        # The brain migrate verb is intentionally NOT in this
        # dispatcher (single-surface under kaizen-brain). Usage text
        # should point users at the canonical entry.
        result = _run("--help")
        self.assertIn("kaizen-brain migrate", result.stdout)

    def test_usage_mentions_code_lift_pointer(self):
        # Code-lift moved out in Tier-2 commit A. Usage text should
        # point users at the new name.
        result = _run("--help")
        self.assertIn("kaizen-code-lift", result.stdout)


class TestUnknownVerb(unittest.TestCase):
    def test_unknown_verb_exits_2_with_listing(self):
        result = _run("brain")  # brain is intentionally excluded
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown verb", result.stderr)
        self.assertIn("'brain'", result.stderr)
        self.assertIn("path", result.stderr)
        self.assertIn("legacy", result.stderr)

    def test_unknown_verb_with_args_still_exits_2(self):
        result = _run("does-not-exist", "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown verb", result.stderr)


class TestDispatchPath(unittest.TestCase):
    """path verb → path_migrate.py. Uses --help so no side effects."""

    def test_path_help_reaches_path_migrate(self):
        result = _run("path", "--help")
        # path_migrate.py's argparse owns the surface; its --help
        # mentions the path-migrate-specific subcommands.
        self.assertEqual(result.returncode, 0)
        # path_migrate.py prog is "kaizen-path-migrate" historically;
        # what matters is the dispatch worked (verb subcommands appear).
        self.assertTrue(
            "status" in result.stdout or "apply" in result.stdout,
            f"path_migrate help missing expected verbs; got:\n{result.stdout}",
        )


class TestDispatchLegacy(unittest.TestCase):
    """legacy verb → migrate_paths.sh. Uses --dry-run for hermeticity."""

    def test_legacy_dry_run_reaches_migrate_paths_sh(self):
        # migrate_paths.sh --dry-run is read-only and prints what would move.
        result = _run("legacy", "--dry-run")
        # Exit code may be 0 (clean) or whatever migrate_paths.sh
        # returns; the key signal is that the dispatch produced output
        # from migrate_paths.sh (not from migrate.py itself).
        # Specifically, migrate.py's usage text is NOT present.
        self.assertNotIn("kaizen-migrate: unknown verb", result.stderr)
        self.assertNotIn(
            "usage: kaizen-migrate <verb>",
            result.stdout,
            "legacy verb should reach migrate_paths.sh, not echo dispatcher usage",
        )


class TestConsolidatedCliParentHeader(unittest.TestCase):
    """Iron-law contract: dispatched scripts declare the parent."""

    def test_path_migrate_has_consolidated_cli_parent_header(self):
        body = (_SCRIPTS / "path_migrate.py").read_text(encoding="utf-8")
        self.assertIn("# consolidated-cli-parent: migrate", body[:200])

    def test_migrate_paths_sh_has_consolidated_cli_parent_header(self):
        body = (_SCRIPTS / "migrate_paths.sh").read_text(encoding="utf-8")
        self.assertIn("# consolidated-cli-parent: migrate", body[:200])


class TestDispatcherCompiles(unittest.TestCase):
    """Catches syntax errors in CI envs that lack runtime deps."""

    def test_migrate_module_parses(self):
        body = _MIGRATE.read_text(encoding="utf-8")
        compile(body, str(_MIGRATE), "exec")


if __name__ == "__main__":
    unittest.main()
