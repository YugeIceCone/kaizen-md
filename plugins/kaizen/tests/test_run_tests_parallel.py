"""TDD — scripts/run_tests_parallel.py — parallel test-file runner.

Pattern lifted from clever-lama-mcp's ParallelBashRunnerNode
(BoundedAsyncParallelBatchNode + asyncio.Semaphore). Per the
plugin's KISS preference we don't drag in the whole Node+Flow
framework for a one-shot runner — just the bounded-async-fan-out
shape. Speeds ci-gate --full from ~70s to ~8s on 32 threads.
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
_SCRIPT = _KZ_DIR / "scripts/tests/run_tests_parallel.py"


def _load():
    spec = importlib.util.spec_from_file_location("rtp", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rtp"] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_tests(tmp: Path, *, n_pass: int = 2, n_fail: int = 0) -> Path:
    """Drop N tiny unittest files into tmp/tests/. Returns the tests dir."""
    tdir = tmp / "tests"
    tdir.mkdir()
    (tdir / "__init__.py").write_text("")
    for i in range(n_pass):
        (tdir / f"test_pass_{i}.py").write_text(textwrap.dedent(f"""\
            import unittest
            class T(unittest.TestCase):
                def test_{i}(self):
                    self.assertEqual(1+1, 2)
            """))
    for i in range(n_fail):
        (tdir / f"test_fail_{i}.py").write_text(textwrap.dedent(f"""\
            import unittest
            class T(unittest.TestCase):
                def test_{i}(self):
                    self.assertTrue(False, "intentional fail {i}")
            """))
    return tdir


class TestDiscoverTestModules(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_discovers_test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=3)
            mods = self.mod.discover_test_modules(Path(tmp) / "tests")
        self.assertEqual(len(mods), 3)
        # Module names as `tests.<stem>`
        self.assertTrue(all(m.startswith("tests.test_pass_") for m in mods))

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp) / "tests"
            tdir.mkdir()
            self.assertEqual(self.mod.discover_test_modules(tdir), [])

    def test_missing_dir_returns_empty(self):
        self.assertEqual(self.mod.discover_test_modules(Path("/nonexistent")), [])


class TestRunParallel(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def _invoke(self, tmp_root: Path, *, extra_env: dict | None = None) -> tuple[int, str, str]:
        env = {**os.environ, **(extra_env or {})}
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "--root", str(tmp_root),
             "--tests-dir", "tests"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_all_pass_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=3)
            rc, out, _err = self._invoke(Path(tmp))
        self.assertEqual(rc, 0, out)
        self.assertIn("3 passed", out)

    def test_any_fail_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=2, n_fail=1)
            rc, out, _err = self._invoke(Path(tmp))
        self.assertNotEqual(rc, 0)
        # The failing module is named so users can find it
        self.assertIn("test_fail_0", out + _err)

    def test_concurrency_env_knob_honored(self):
        """KAIZEN_TEST_CONCURRENCY caps the Semaphore."""
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=2)
            rc, out, _ = self._invoke(
                Path(tmp), extra_env={"KAIZEN_TEST_CONCURRENCY": "4"},
            )
        self.assertEqual(rc, 0)
        # The script reports the resolved concurrency for observability
        self.assertRegex(out, r"concurrency[=:\s]+4")

    def test_empty_test_dir_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tests").mkdir()
            rc, out, _ = self._invoke(Path(tmp))
        self.assertEqual(rc, 0)
        self.assertIn("0 passed", out)


class TestModulesFlag(unittest.TestCase):
    """`--modules MOD,MOD,...` bypasses discovery and runs only the
    named modules. Powers pre-commit.sh's affected-tests subset."""

    def _invoke(self, root: Path, modules: str) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT),
             "--root", str(root), "--tests-dir", "tests",
             "--modules", modules],
            capture_output=True, text=True, timeout=30,
            env=os.environ.copy(),
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_modules_flag_runs_only_named_modules(self):
        """Drop 3 test files; --modules picks 1 → only 1 runs."""
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=3)
            rc, out, _ = self._invoke(Path(tmp), "tests.test_pass_1")
        self.assertEqual(rc, 0, out)
        # Header reports 1 file, not 3
        self.assertRegex(out, r"\b1 test files?\b|\b1 modules?\b")
        self.assertIn("1 passed", out)

    def test_modules_flag_propagates_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=1, n_fail=1)
            rc, out, _err = self._invoke(Path(tmp), "tests.test_fail_0")
        self.assertNotEqual(rc, 0)
        self.assertIn("test_fail_0", out + _err)

    def test_modules_flag_ignores_unknown_with_warning(self):
        """Unknown module → unittest exits non-zero (informative)."""
        with tempfile.TemporaryDirectory() as tmp:
            _seed_tests(Path(tmp), n_pass=1)
            rc, _out, _err = self._invoke(Path(tmp), "tests.nonexistent_module")
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
