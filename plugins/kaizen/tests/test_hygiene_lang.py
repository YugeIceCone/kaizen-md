"""Tests for X5 — per-language composite hygiene.

Uses subprocess + tool-presence stubs so tests never invoke real
cargo/pip-audit/npm/govulncheck on the test runner.

Run:
    python3 -m unittest tests.test_hygiene_lang -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _hygiene_lang as h  # noqa: E402

def _make_repo(tmp: Path, manifests: list[str]) -> Path:
    """Touch the given manifest files in tmp to mark languages present."""
    for m in manifests:
        (tmp / m).write_text("")
    return tmp

def _stub_runner(ret_map: dict):
    """Build a subprocess-stub. ret_map: cmd-prefix → (rc, stdout, stderr)."""
    def runner(cmd, cwd, timeout):
        key = cmd[0] if cmd else ""
        if key in ret_map:
            return ret_map[key]
        for k, v in ret_map.items():
            if " ".join(cmd).startswith(k):
                return v
        return 0, "", ""
    return runner

def _all_present(_tool):
    return True

def _none_present(_tool):
    return False

# ─── Detection ────────────────────────────────────────────────────────

class TestDetectLanguages(unittest.TestCase):
    def test_rust_only(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["Cargo.toml"])
            self.assertEqual(h.detect_languages(tmp), ["rust"])

    def test_polyglot(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), [
                "Cargo.toml", "pyproject.toml", "package.json",
            ])
            self.assertEqual(
                set(h.detect_languages(tmp)),
                {"rust", "python", "javascript"},
            )

    def test_empty_repo(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(h.detect_languages(Path(td)), [])

    def test_python_via_requirements_txt(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["requirements.txt"])
            self.assertIn("python", h.detect_languages(tmp))

    def test_typescript_via_tsconfig(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["tsconfig.json"])
            self.assertIn("typescript", h.detect_languages(tmp))

    def test_go_via_go_mod(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["go.mod"])
            self.assertIn("go", h.detect_languages(tmp))

# ─── Probe execution ─────────────────────────────────────────────────

class TestRunProbe(unittest.TestCase):
    def test_tool_missing_returns_ok_with_flag(self):
        with tempfile.TemporaryDirectory() as td:
            probe = h.Probe("test", "nonexistent-tool-xyz", ["nonexistent-tool-xyz"])
            f = h.run_probe(probe, Path(td), tool_present_fn=_none_present)
            self.assertTrue(f.ok)
            self.assertTrue(f.tool_missing)
            self.assertIn("not installed", f.note)

    def test_clean_exit_returns_ok(self):
        with tempfile.TemporaryDirectory() as td:
            probe = h.Probe("test", "tool", ["tool"])
            runner = _stub_runner({"tool": (0, "clean", "")})
            f = h.run_probe(probe, Path(td), runner=runner,
                            tool_present_fn=_all_present)
            self.assertTrue(f.ok)
            self.assertFalse(f.tool_missing)

    def test_nonzero_exit_returns_finding(self):
        with tempfile.TemporaryDirectory() as td:
            probe = h.Probe("test", "tool", ["tool"])
            runner = _stub_runner({"tool": (1, "", "vulnerability X found")})
            f = h.run_probe(probe, Path(td), runner=runner,
                            tool_present_fn=_all_present)
            self.assertFalse(f.ok)
            self.assertFalse(f.tool_missing)
            self.assertIn("vulnerability X found", f.detail)

# ─── Composite ────────────────────────────────────────────────────────

class TestRunComposite(unittest.TestCase):
    def test_polyglot_runs_all_languages(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), [
                "Cargo.toml", "pyproject.toml", "package.json",
            ])
            runner = _stub_runner({})  # all clean
            result = h.run_composite(
                tmp, runner=runner, tool_present_fn=_all_present,
            )
            langs_found = {f.language for f in result.findings}
            self.assertEqual(langs_found, {"rust", "python", "javascript"})
            self.assertTrue(result.ok)

    def test_hard_failure_breaks_ok(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["Cargo.toml"])
            runner = _stub_runner({"cargo": (1, "", "RUSTSEC-2024-0001 found")})
            result = h.run_composite(
                tmp, runner=runner, tool_present_fn=_all_present,
            )
            self.assertFalse(result.ok)
            self.assertEqual(len(result.hard_failures), 1)

    def test_missing_tools_keep_ok_true(self):
        """Tool-missing skips don't break the overall CI gate."""
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["Cargo.toml", "pyproject.toml"])
            result = h.run_composite(
                tmp, runner=_stub_runner({}), tool_present_fn=_none_present,
            )
            self.assertTrue(result.ok)
            self.assertGreater(result.tool_missing_count, 0)
            self.assertEqual(result.hard_failures, [])

    def test_empty_repo_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            result = h.run_composite(Path(td))
            self.assertEqual(result.findings, [])
            self.assertTrue(result.ok)

# ─── Reporting ───────────────────────────────────────────────────────

class TestFormatReport(unittest.TestCase):
    def test_text_format_lists_findings(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["Cargo.toml"])
            runner = _stub_runner({"cargo": (1, "", "fail")})
            result = h.run_composite(
                tmp, runner=runner, tool_present_fn=_all_present,
            )
            text = h.format_report(result)
            self.assertIn("rust", text)
            self.assertIn("cargo-audit", text)
            self.assertIn("FAIL", text)

    def test_json_format(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["Cargo.toml"])
            result = h.run_composite(
                tmp, runner=_stub_runner({}), tool_present_fn=_all_present,
            )
            text = h.format_report(result, json_mode=True)
            data = json.loads(text)
            self.assertIn("findings", data)
            self.assertIn("languages", data)
            self.assertEqual(data["languages"], ["rust"])

    def test_ok_text_when_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _make_repo(Path(td), ["Cargo.toml"])
            result = h.run_composite(
                tmp, runner=_stub_runner({}), tool_present_fn=_all_present,
            )
            text = h.format_report(result)
            self.assertIn("OK", text)

if __name__ == "__main__":
    unittest.main()
