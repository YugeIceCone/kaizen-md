"""Smoke tests for the 5 new CLI shortcuts (status / health / backup /
workflow / setup) added by the 2026-05-18 surface-gap audit.

Each `kaizen <X>` verb dispatches to `bin/kaizen-<X>` (see bin/kaizen).
These wrappers must:
  1. exist + be executable
  2. resolve their plugin root via the readlink idiom (no symlink bug)
  3. exec their backing script + return its exit code cleanly

Side-effect-safe args only — kaizen-setup with no args runs install, so
we exercise it via the read-only `env path` subcmd instead.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"


# (bin_name, safe_args_to_pass) — keep args read-only.
SHORTCUTS = [
    ("kaizen-status",   []),               # status.sh is read-only diagnostic
    ("kaizen-health",   []),               # health.sh is read-only; exits 0 or 1
    ("kaizen-backup",   ["list"]),         # explicit list (safest); no args also defaults to list
    ("kaizen-workflow", ["show"]),         # show is the read-only verb
    ("kaizen-setup",    ["env", "path"]),  # env subcmd's safest verb (prints path, no install)
]


def _invoke_through_symlink(bin_name: str, args: list[str]) -> subprocess.CompletedProcess:
    real = BIN_DIR / bin_name
    with tempfile.TemporaryDirectory() as td:
        link = Path(td) / bin_name
        link.symlink_to(real)
        env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
        return subprocess.run(
            [str(link), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )


class TestCliShortcuts(unittest.TestCase):
    def test_all_shortcut_bins_exist_and_executable(self):
        for bin_name, _ in SHORTCUTS:
            path = BIN_DIR / bin_name
            self.assertTrue(path.is_file(), f"{bin_name} missing in bin/")
            self.assertTrue(os.access(path, os.X_OK), f"{bin_name} not executable")

    def test_each_shortcut_resolves_through_symlink(self):
        """Each new wrapper must work when invoked through a symlink
        (mirrors /kaizen:setup symlinking into ~/.local/bin/)."""
        failures = []
        for bin_name, args in SHORTCUTS:
            try:
                r = _invoke_through_symlink(bin_name, args)
            except Exception as e:
                failures.append(f"{bin_name}: invocation exception {e!r}")
                continue
            # Symlink-resolution failure → "No such file" or "command not found"
            combined = r.stdout + r.stderr
            if "No such file or directory" in combined and "_plugin_root.sh" in combined:
                failures.append(f"{bin_name}: symlink-resolution broken — {r.stderr.strip()}")
            # Hard Python traceback = unrelated regression we want to catch
            if "Traceback (most recent call last)" in r.stderr:
                failures.append(f"{bin_name}: tracebacked — {r.stderr.strip()[:200]}")
        self.assertFalse(
            failures,
            "the following shortcuts failed symlink invocation:\n"
            + "\n".join(failures),
        )

    def test_each_shortcut_uses_readlink_idiom(self):
        """Source-level guard against future regression to the broken
        $_BIN_DIR pattern."""
        for bin_name, _ in SHORTCUTS:
            content = (BIN_DIR / bin_name).read_text()
            self.assertIn(
                "readlink -f",
                content,
                f"{bin_name} missing readlink resolver — would break under symlink",
            )

    def test_kaizen_setup_env_path_prints_kaizen_env_sh(self):
        """Smoke the env subcmd path branch — should print the absolute
        path to kaizen-env.sh."""
        r = _invoke_through_symlink("kaizen-setup", ["env", "path"])
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("kaizen-env.sh", r.stdout)


if __name__ == "__main__":
    unittest.main()
