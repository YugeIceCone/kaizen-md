"""TDD — scripts/_affected_tests.py — derive affected tests from
staged file list. Powers pre-commit.sh's optional test-gate.

Contract (pure function):
  derive_modules(staged_files, repo_root, plugin_root) -> tuple[list[str], str]
    Returns (modules, reason).
    - modules = ["tests.test_foo", ...] OR the special sentinel ["FULL"]
      (caller dispatches `run_tests_parallel.py` with no --modules to
      run the entire suite via discovery).
    - reason = one-line human-readable explanation for the gate output.
    - Empty list = no Python files staged; caller skips.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/tests/_affected_tests.py"


def _load():
    spec = importlib.util.spec_from_file_location("at", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["at"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed(tmp: Path) -> Path:
    """Lay out a minimal plugin-shape tree under tmp:
        plugins/kaizen/
          scripts/util/
            foo.py
            _helper.py
            bar.py
          tests/
            test_foo.py
            (test_bar.py intentionally missing)
    """
    plugin = tmp / "plugins/kaizen"
    scripts = plugin / "scripts/util"
    tests = plugin / "tests"
    scripts.mkdir(parents=True)
    tests.mkdir(parents=True)
    (scripts / "foo.py").write_text("def foo(): pass\n")
    (scripts / "_helper.py").write_text("def h(): pass\n")
    (scripts / "bar.py").write_text("def bar(): pass\n")
    (tests / "__init__.py").write_text("")
    (tests / "test_foo.py").write_text("# paired\n")
    return plugin


class TestDeriveModules(unittest.TestCase):
    def setUp(self):
        self.at = _load()

    def test_empty_staged_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=[], repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, [])
        self.assertIn("no", reason.lower())

    def test_no_python_files_returns_empty(self):
        """README/SH-only commits → skip cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=["README.md", "scripts/x.sh"],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, [])
        self.assertRegex(reason.lower(), r"no python|no \.py")

    def test_direct_map_script_to_paired_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=["plugins/kaizen/scripts/util/foo.py"],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, ["tests.test_foo"])
        self.assertIn("direct", reason.lower())

    def test_unmapped_script_falls_back_to_full(self):
        """scripts/bar.py has no tests/test_bar.py → full suite."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=["plugins/kaizen/scripts/util/bar.py"],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, ["FULL"])
        self.assertRegex(reason.lower(), r"no paired|unmapped|full")

    def test_private_helper_triggers_full(self):
        """_helper.py fans out unpredictably → full suite."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=["plugins/kaizen/scripts/util/_helper.py"],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, ["FULL"])
        self.assertIn("private", reason.lower())

    def test_test_file_staged_runs_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=["plugins/kaizen/tests/test_foo.py"],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, ["tests.test_foo"])
        # Reason is short + human-readable; precise wording doesn't matter,
        # only the resolved module set does.
        self.assertTrue(reason)

    def test_mixed_staging_unions_modules(self):
        """script + paired test together → just the test (deduplicated)."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=[
                    "plugins/kaizen/scripts/util/foo.py",
                    "plugins/kaizen/tests/test_foo.py",
                ],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(sorted(mods), ["tests.test_foo"])

    def test_private_helper_dominates_direct_map(self):
        """Private helper present → full suite even if other files are mapped."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            mods, reason = self.at.derive_modules(
                staged_files=[
                    "plugins/kaizen/scripts/util/foo.py",
                    "plugins/kaizen/scripts/util/_helper.py",
                ],
                repo_root=Path(tmp), plugin_root=plugin,
            )
        self.assertEqual(mods, ["FULL"])
        self.assertIn("private", reason.lower())


class TestCli(unittest.TestCase):
    """The script is also invokable from bash — pre-commit.sh calls it
    with the staged-file list on stdin (one path per line) and reads
    a single line back: comma-sep modules, the literal FULL, or empty."""

    def _invoke(self, plugin: Path, staged_stdin: str) -> tuple[int, str, str]:
        env = {**os.environ, "KAIZEN_AFFECTED_PLUGIN_ROOT": str(plugin)}
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=staged_stdin, capture_output=True, text=True,
            timeout=10, env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_stdin_no_python_emits_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            rc, out, _ = self._invoke(plugin, "README.md\nfoo.sh\n")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "")

    def test_stdin_direct_map_emits_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            rc, out, _ = self._invoke(
                plugin, "plugins/kaizen/scripts/util/foo.py\n",
            )
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "tests.test_foo")

    def test_stdin_private_helper_emits_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = _seed(Path(tmp))
            rc, out, _ = self._invoke(
                plugin, "plugins/kaizen/scripts/util/_helper.py\n",
            )
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "FULL")


if __name__ == "__main__":
    unittest.main()
