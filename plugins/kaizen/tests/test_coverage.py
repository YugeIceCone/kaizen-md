"""Tests for kaizen-coverage — the mechanical 1:1 code-to-test mapper.

The tool walks plugins/kaizen/skills/workflow/scripts/*.py (excluding
private `_<x>.py` helpers + `<x>_mcp.py` MCP servers) and reports
which scripts have a matching `tests/test_<x>*.py` and which don't.

This is a stdlib-only feature (no coverage.py / pytest-cov required).
The goal is the 1:1 ratio metric: every public script should have at
least one test file pointing at it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/quality/coverage.py"


def _run(*args, root: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the script. `--root` overrides plugin root for tests.
    Top-level --root must precede the subcommand position."""
    cmd = [sys.executable, str(_SCRIPT)]
    if root is not None:
        cmd.extend(["--root", str(root)])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10)


class TestScriptExists(unittest.TestCase):
    def test_coverage_script_present(self):
        self.assertTrue(_SCRIPT.is_file(), f"missing: {_SCRIPT}")

    def test_script_parses(self):
        with open(_SCRIPT, "r") as f:
            compile(f.read(), str(_SCRIPT), "exec")


class SyntheticRootBase(unittest.TestCase):
    """Build a synthetic plugin tree so tests don't depend on the real one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Post DOMAIN-shells sweep: production code lives under
        # scripts/<cluster>/. Use a fake cluster for the synthetic root.
        self.scripts = self.root / "scripts" / "util"
        self.tests = self.root / "tests"
        self.scripts.mkdir(parents=True)
        self.tests.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _src(self, stem: str, body: str = "pass\n"):
        (self.scripts / f"{stem}.py").write_text(body)

    def _test(self, stem: str, body: str = "pass\n"):
        (self.tests / f"test_{stem}.py").write_text(body)


class TestSummaryRatio(SyntheticRootBase):
    def test_all_covered_reports_100pct(self):
        self._src("alpha")
        self._test("alpha")
        r = _run("summary", "--json", root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["covered"], 1)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["ratio_pct"], 100)
        self.assertEqual(data["uncovered"], [])

    def test_half_covered_reports_50pct(self):
        self._src("alpha"); self._test("alpha")
        self._src("beta")  # no test
        r = _run("summary", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(data["covered"], 1)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["ratio_pct"], 50)
        self.assertEqual(data["uncovered"], ["beta"])

    def test_private_helpers_excluded(self):
        """_<x>.py is a private helper — not part of the coverage denominator."""
        self._src("_private")
        r = _run("summary", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], 0)

    def test_mcp_servers_excluded(self):
        """<x>_mcp.py is tested via its parent feature — not its own slot."""
        self._src("alpha_mcp")
        r = _run("summary", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], 0)


class TestPrefixMatching(SyntheticRootBase):
    def test_op_script_covered_by_parent_test(self):
        """brain_index.py covered by test_brain*.py (parent matches)."""
        self._src("brain_index")
        self._test("brain")
        r = _run("summary", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(data["covered"], 1)
        self.assertEqual(data["uncovered"], [])

    def test_op_script_covered_by_explicit_test(self):
        self._src("brain_index")
        self._test("brain_index")
        r = _run("summary", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(data["covered"], 1)


class TestGapsSubcommand(SyntheticRootBase):
    def test_gaps_lists_only_uncovered(self):
        self._src("alpha"); self._test("alpha")
        self._src("beta")
        self._src("gamma")
        r = _run("gaps", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(set(data["uncovered"]), {"beta", "gamma"})
        self.assertNotIn("alpha", data["uncovered"])

    def test_gaps_text_output_one_per_line(self):
        self._src("alpha")
        self._src("beta")
        r = _run("gaps", root=self.root)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        self.assertEqual(sorted(lines), ["alpha", "beta"])


class TestReportSubcommand(SyntheticRootBase):
    def test_report_includes_both_covered_and_uncovered(self):
        self._src("alpha"); self._test("alpha")
        self._src("beta")
        r = _run("report", "--json", root=self.root)
        data = json.loads(r.stdout)
        self.assertEqual(data["summary"]["covered"], 1)
        self.assertEqual(data["summary"]["uncovered_count"], 1)
        # Detail rows
        rows = {row["script"]: row for row in data["scripts"]}
        self.assertTrue(rows["alpha"]["covered"])
        self.assertFalse(rows["beta"]["covered"])


class TestExitCodes(SyntheticRootBase):
    def test_summary_exit_0_when_all_covered(self):
        self._src("alpha"); self._test("alpha")
        r = _run("summary", root=self.root)
        self.assertEqual(r.returncode, 0)

    def test_gaps_exit_1_when_uncovered(self):
        """gaps exits 1 when there's anything to report — for CI gating."""
        self._src("alpha")
        r = _run("gaps", root=self.root)
        self.assertEqual(r.returncode, 1)

    def test_gaps_exit_0_when_clean(self):
        self._src("alpha"); self._test("alpha")
        r = _run("gaps", root=self.root)
        self.assertEqual(r.returncode, 0)


class TestRealPluginRoot(unittest.TestCase):
    """Smoke test against the real kaizen plugin — confirms the tool runs
    end-to-end without crashing. Doesn't assert specific numbers (those
    drift as the plugin grows)."""

    def test_summary_against_real_plugin_returns_ratio(self):
        r = _run("summary", "--json")  # no --root → uses plugin auto-discovery
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("ratio_pct", data)
        self.assertGreater(data["total"], 50)  # plugin has many scripts
        self.assertGreaterEqual(data["ratio_pct"], 75)  # current baseline ~89%


if __name__ == "__main__":
    unittest.main()
