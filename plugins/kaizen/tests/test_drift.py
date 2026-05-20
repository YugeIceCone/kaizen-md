"""Tests for X2 — structural-drift detector + M2 MCP wrapper.

Builds tiny JSON profile pairs in tmpdir and verifies the diff
classification: items added/removed, deps added/removed, LOC/tests
delta, NEW/REMOVED unit detection.

Run:
    python3 -m unittest tests.test_drift -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "mcp"))

import _drift as d  # noqa: E402

def _profile(items=None, deps=None, loc=0, tests=0):
    return {
        "files": [{"path": "src/lib.rs",
                   "items": [{"kind": k, "name": n} for k, n in (items or [])]}],
        "deps": deps or [],
        "total_loc": loc,
        "total_tests": tests,
    }

def _write(profile_dir: Path, name: str, p: dict):
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{name}.json").write_text(json.dumps(p))

# ─── Collectors ────────────────────────────────────────────────────

class TestCollectors(unittest.TestCase):
    def test_collect_items_returns_kind_name_pairs(self):
        p = _profile(items=[("fn", "foo"), ("struct", "Bar")])
        self.assertEqual(d.collect_items(p), {"fn foo", "struct Bar"})

    def test_collect_items_skips_empty_names(self):
        p = {"files": [{"items": [{"kind": "fn", "name": ""}, {"kind": "x"}]}]}
        self.assertEqual(d.collect_items(p), set())

    def test_collect_deps_string_list(self):
        self.assertEqual(
            d.collect_deps({"deps": ["a", "b"]}), {"a", "b"},
        )

    def test_collect_deps_dict_list(self):
        self.assertEqual(
            d.collect_deps({"deps": [{"name": "a"}, {"name": "b"}]}),
            {"a", "b"},
        )

    def test_collect_deps_missing_returns_empty(self):
        self.assertEqual(d.collect_deps({}), set())

# ─── compare_units ─────────────────────────────────────────────────

class TestCompareUnits(unittest.TestCase):
    def test_no_changes(self):
        b = _profile(items=[("fn", "foo")], deps=["a"], loc=100, tests=10)
        c = _profile(items=[("fn", "foo")], deps=["a"], loc=100, tests=10)
        ud = d.compare_units("core", b, c)
        self.assertTrue(ud.is_empty())

    def test_item_added(self):
        b = _profile(items=[("fn", "foo")])
        c = _profile(items=[("fn", "foo"), ("fn", "bar")])
        ud = d.compare_units("core", b, c)
        self.assertEqual(ud.items_added, ["fn bar"])
        self.assertEqual(ud.items_removed, [])

    def test_item_removed(self):
        b = _profile(items=[("fn", "foo"), ("fn", "bar")])
        c = _profile(items=[("fn", "foo")])
        ud = d.compare_units("core", b, c)
        self.assertEqual(ud.items_removed, ["fn bar"])

    def test_dep_added(self):
        b = _profile(deps=["a"])
        c = _profile(deps=["a", "b"])
        ud = d.compare_units("core", b, c)
        self.assertEqual(ud.deps_added, ["b"])

    def test_loc_delta(self):
        b = _profile(loc=100)
        c = _profile(loc=150)
        ud = d.compare_units("core", b, c)
        self.assertEqual(ud.loc_delta, 50)

    def test_negative_loc_delta(self):
        b = _profile(loc=200)
        c = _profile(loc=150)
        ud = d.compare_units("core", b, c)
        self.assertEqual(ud.loc_delta, -50)

    def test_tests_delta(self):
        b = _profile(tests=5)
        c = _profile(tests=10)
        ud = d.compare_units("core", b, c)
        self.assertEqual(ud.tests_delta, 5)

# ─── run_check end-to-end ──────────────────────────────────────────

class TestRunCheck(unittest.TestCase):
    def test_changed_unit_appears_in_report(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "baseline", tmp / "current"
            _write(bdir, "core", _profile(items=[("fn", "old")]))
            _write(cdir, "core", _profile(items=[("fn", "new")]))
            r = d.run_check(bdir, cdir)
            self.assertEqual(len(r.changed), 1)
            self.assertEqual(r.changed[0].items_added, ["fn new"])
            self.assertEqual(r.changed[0].items_removed, ["fn old"])

    def test_new_unit_added(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "baseline", tmp / "current"
            _write(bdir, "core", _profile())
            _write(cdir, "core", _profile())
            _write(cdir, "shiny-new", _profile(items=[("fn", "ship")]))
            r = d.run_check(bdir, cdir)
            self.assertEqual(r.added_units, ["shiny-new"])
            self.assertEqual(r.changed, [])

    def test_removed_unit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "baseline", tmp / "current"
            _write(bdir, "core", _profile())
            _write(bdir, "retired", _profile())
            _write(cdir, "core", _profile())
            r = d.run_check(bdir, cdir)
            self.assertEqual(r.removed_units, ["retired"])

    def test_only_filter(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "baseline", tmp / "current"
            _write(bdir, "core", _profile(items=[("fn", "old")]))
            _write(cdir, "core", _profile(items=[("fn", "new")]))
            _write(bdir, "cli", _profile(items=[("fn", "x")]))
            _write(cdir, "cli", _profile(items=[("fn", "y")]))
            r = d.run_check(bdir, cdir, only="core")
            self.assertEqual(len(r.changed), 1)
            self.assertEqual(r.changed[0].unit, "core")

    def test_no_drift_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "baseline", tmp / "current"
            _write(bdir, "core", _profile(items=[("fn", "same")]))
            _write(cdir, "core", _profile(items=[("fn", "same")]))
            r = d.run_check(bdir, cdir)
            self.assertTrue(r.is_empty)
            self.assertEqual(r.total, 0)

# ─── record_baseline ──────────────────────────────────────────────

class TestRecordBaseline(unittest.TestCase):
    def test_copies_all_json_files(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            current = tmp / "current"
            baseline = tmp / "baseline"
            _write(current, "core", _profile(loc=100))
            _write(current, "cli", _profile(loc=200))
            (current / "skip-me.txt").write_text("not json")
            result = d.record_baseline(current, baseline)
            self.assertEqual(result["copied"], 2)
            self.assertTrue((baseline / "core.json").is_file())
            self.assertTrue((baseline / "cli.json").is_file())
            self.assertFalse((baseline / "skip-me.txt").is_file())

    def test_missing_current_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                d.record_baseline(Path(td) / "no-such", Path(td) / "bl")

    def test_creates_baseline_dir(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            current = tmp / "current"
            baseline = tmp / "deep" / "nested" / "baseline"
            _write(current, "core", _profile())
            d.record_baseline(current, baseline)
            self.assertTrue(baseline.is_dir())

# ─── Reporting ────────────────────────────────────────────────────

class TestFormatReport(unittest.TestCase):
    def test_text_lists_added_units(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "b", tmp / "c"
            _write(cdir, "fresh", _profile())
            bdir.mkdir()
            r = d.run_check(bdir, cdir)
            text = d.format_report(r)
            self.assertIn("fresh", text)
            self.assertIn("NEW", text)

    def test_json_format(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bdir, cdir = tmp / "b", tmp / "c"
            _write(bdir, "core", _profile(items=[("fn", "x")]))
            _write(cdir, "core", _profile(items=[("fn", "y")]))
            r = d.run_check(bdir, cdir)
            data = json.loads(d.format_report(r, json_mode=True))
            self.assertEqual(len(data["changed"]), 1)
            self.assertEqual(data["total"], 1)

# ─── MCP ──────────────────────────────────────────────────────────

class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()

class TestDriftMcp(_CwdMixin, unittest.TestCase):
    def _import(self):
        for m in ("drift_mcp", "_drift"):
            if m in sys.modules:
                del sys.modules[m]
        import drift_mcp
        return drift_mcp

    def test_drift_status_no_baseline(self):
        m = self._import()
        out = asyncio.run(m.drift_status())
        self.assertFalse(out["baseline_present"])
        self.assertEqual(out["baseline_count"], 0)

    def test_drift_record_then_check_clean(self):
        # Build a tiny docs/crates dir
        crates = self.tmp / "docs" / "crates"
        _write(crates, "core", _profile(items=[("fn", "foo")]))
        m = self._import()
        rec = asyncio.run(m.drift_record_baseline())
        self.assertEqual(rec["copied"], 1)
        chk = asyncio.run(m.drift_check())
        self.assertEqual(chk["total"], 0)

    def test_drift_check_detects_drift(self):
        crates = self.tmp / "docs" / "crates"
        _write(crates, "core", _profile(items=[("fn", "foo")]))
        m = self._import()
        asyncio.run(m.drift_record_baseline())
        # Now modify current to introduce drift
        _write(crates, "core", _profile(items=[("fn", "foo"), ("fn", "bar")]))
        chk = asyncio.run(m.drift_check(fail_on_drift=True))
        self.assertGreater(chk["total"], 0)
        self.assertTrue(chk.get("gate_failed"))

    def test_drift_explain_unchanged(self):
        crates = self.tmp / "docs" / "crates"
        _write(crates, "core", _profile())
        m = self._import()
        asyncio.run(m.drift_record_baseline())
        out = asyncio.run(m.drift_explain("core"))
        self.assertTrue(out.get("unchanged"))

class TestRegistration(unittest.TestCase):
    def test_drift_in_mcp_json(self):
        data = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
        # All domain servers are composed through the kaizen gateway
        self.assertIn("kaizen", data["mcpServers"])
        import gateway
        module_names = [m for _, m in gateway.SUBSERVERS]
        self.assertIn("drift_mcp", module_names)

if __name__ == "__main__":
    unittest.main()
