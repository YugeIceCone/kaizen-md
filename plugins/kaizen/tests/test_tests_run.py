"""Tests for kaizen-test — unified test harness.

Per user 2026-05-18 sid 32bad1f7 — "consolidate into a custom testing
harness / runner cli ... tdd kiss dry solid".

Audit findings (this session):
  - 287 test files; 282 unittest.TestCase + 5 pytest-style mix
  - `run_tests_parallel.py` uses 32 cores correctly but bottlenecks on
    the slowest single file (e.g. test_learning_log = 33s of 32s wall)
  - 5 entry points today (unittest discover / pytest / parallel runner /
    legacy _tests.py / bash) — KISS goal: collapse to one CLI

Design contract:
  PROGRAMMABLE  — classify_style / dispatch_cmd / bench_report are pure
  REPRODUCIBLE  — same (files, style) → same dispatch argv
  CONSISTENT    — every subcommand emits envelope when --json passed
  DETERMINISTIC — no wall-clock peek in pure layer
  REUSABLE      — adapter pattern: new runners plug in without changing CLI
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_RUNNER = _KZ / "skills/workflow/scripts/tests_run.py"

sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
import _tests_run as _tr  # noqa: E402


# ─── classify_style — pure ─────────────────────────────────────────────

class TestClassifyStyle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, body: str) -> Path:
        p = self.tmp / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_unittest_testcase_parent(self):
        p = self._write("test_x.py",
                         "import unittest\nclass TestX(unittest.TestCase):\n"
                         "    def test_a(self): pass\n")
        self.assertEqual(_tr.classify_style(p), "unittest")

    def test_pytest_bare_class(self):
        p = self._write("test_x.py",
                         "class TestX:\n    def test_a(self): assert True\n")
        self.assertEqual(_tr.classify_style(p), "pytest")

    def test_pytest_module_level_functions(self):
        p = self._write("test_x.py",
                         "def test_a():\n    assert 1 == 1\n")
        self.assertEqual(_tr.classify_style(p), "pytest")

    def test_bash_shell_file(self):
        p = self._write("test_x.sh", "#!/usr/bin/env bash\necho ok\n")
        self.assertEqual(_tr.classify_style(p), "bash")

    def test_unittest_when_both_styles_present_prefers_unittest(self):
        # A file that has BOTH `unittest.TestCase` subclass AND a bare
        # class — treat as unittest (it'll run under unittest cleanly).
        p = self._write("test_x.py",
                         "import unittest\nclass A(unittest.TestCase): pass\n"
                         "class TestB: pass\n")
        self.assertEqual(_tr.classify_style(p), "unittest")

    def test_unknown_falls_back_to_unittest(self):
        # Empty / no test markers → assume unittest discovery (matches
        # current behavior — it'll just find 0 tests)
        p = self._write("test_x.py", "# placeholder\n")
        self.assertEqual(_tr.classify_style(p), "unittest")


# ─── dispatch_cmd — pure ───────────────────────────────────────────────

class TestDispatchCmd(unittest.TestCase):
    def test_unittest_emits_module_form(self):
        cmd = _tr.dispatch_cmd(Path("tests/test_foo.py"), style="unittest")
        self.assertIn("-m", cmd)
        self.assertIn("unittest", cmd)
        self.assertIn("tests.test_foo", cmd)

    def test_pytest_emits_path_form(self):
        cmd = _tr.dispatch_cmd(Path("tests/test_foo.py"), style="pytest")
        self.assertIn("-m", cmd)
        self.assertIn("pytest", cmd)
        self.assertIn("-q", cmd)
        self.assertIn("tests/test_foo.py", cmd)

    def test_bash_emits_bash_form(self):
        cmd = _tr.dispatch_cmd(Path("tests/test_x.sh"), style="bash")
        self.assertEqual(cmd[0], "bash")
        self.assertIn("tests/test_x.sh", cmd)


# ─── bench_report — pure ───────────────────────────────────────────────

class TestBenchReport(unittest.TestCase):
    def test_sorts_slowest_first(self):
        results = [("a", 0.1, 0), ("b", 5.0, 0), ("c", 1.0, 0)]
        out = _tr.bench_report(results, top_n=3)
        # Slowest should appear first in the report
        a_pos = out.find("a")
        b_pos = out.find("b")
        self.assertLess(b_pos, a_pos)

    def test_top_n_caps_output(self):
        results = [(f"m{i}", float(i), 0) for i in range(10)]
        out = _tr.bench_report(results, top_n=3)
        # Only top 3 should appear by name
        names_shown = sum(1 for i in range(10) if f"m{i}" in out)
        self.assertEqual(names_shown, 3)

    def test_summary_includes_totals(self):
        results = [("a", 1.0, 0), ("b", 2.0, 0), ("c", 0.5, 1)]
        out = _tr.bench_report(results, top_n=5)
        self.assertIn("3", out)  # 3 files
        # Total sum should appear
        self.assertIn("3.5", out)  # 1.0 + 2.0 + 0.5


# ─── CLI integration ───────────────────────────────────────────────────

class TestRunnerCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.tests_dir = self.tmp / "tests"
        self.tests_dir.mkdir()
        # 1 passing unittest file
        (self.tests_dir / "test_pass.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            "    def test_a(self): self.assertEqual(1, 1)\n",
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_RUNNER), "--root", str(self.tmp), *args],
            capture_output=True, text=True, timeout=30,
            env=os.environ.copy(),
        )

    def test_default_run_passes(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("passed", r.stdout + r.stderr)

    def test_json_output_envelope_shape(self):
        r = self._run("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("passed", data)
        self.assertIn("failed", data)
        self.assertIn("results", data)

    def test_bench_subcommand_sorts_by_time(self):
        # Add a deliberately-slower test — long enough sleep that it
        # reliably beats subprocess cold-start variance on fast machines
        (self.tests_dir / "test_slow.py").write_text(
            "import unittest, time\nclass T(unittest.TestCase):\n"
            "    def test_a(self): time.sleep(1.0); self.assertTrue(True)\n",
            encoding="utf-8")
        r = self._run("bench", "--top-n", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        # test_slow should appear above test_pass in the report
        slow_pos = r.stdout.find("test_slow")
        pass_pos = r.stdout.find("test_pass")
        self.assertGreaterEqual(slow_pos, 0)
        self.assertGreaterEqual(pass_pos, 0)
        self.assertLess(slow_pos, pass_pos)


if __name__ == "__main__":
    unittest.main()
