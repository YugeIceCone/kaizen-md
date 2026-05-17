"""Tests for skills/workflow/scripts/gatekeeper.py and
skills/efficient-tool-use/application/etu_scan.py — the unified gate."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATEKEEPER = _REPO_ROOT / "plugins/kaizen/skills/workflow/scripts/gatekeeper.py"
_ETU_SCAN = _REPO_ROOT / "plugins/kaizen/skills/efficient-tool-use/application/etu_scan.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestEtuScan(unittest.TestCase):
    def setUp(self):
        self.etu = _load("etu_scan_test", _ETU_SCAN)

    def test_scan_detects_known_anti_pattern(self):
        """A bash file with a known anti-pattern (find /) is flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.sh"
            p.write_text("#!/bin/bash\nfind / -name foo\n")
            findings = self.etu.scan_files([p])
            ids = {f.pattern_id for f in findings}
            self.assertIn("find-from-root", ids)

    def test_scan_clean_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "good.sh"
            p.write_text("#!/bin/bash\nset -euo pipefail\necho hello\n")
            findings = self.etu.scan_files([p])
            self.assertEqual(findings, [])

    def test_scan_ignores_non_existent_file(self):
        # Should not crash on a missing path
        findings = self.etu.scan_files([Path("/nonexistent/file.sh")])
        self.assertEqual(findings, [])

    def test_finding_includes_severity_and_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eval.sh"
            p.write_text('#!/bin/bash\neval "$user_input"\n')
            findings = self.etu.scan_files([p])
            self.assertTrue(any(f.severity == "error" for f in findings))
            for f in findings:
                self.assertTrue(f.replacement, "replacement must be non-empty")


class TestGatekeeperAggregator(unittest.TestCase):
    def setUp(self):
        self.gk = _load("gatekeeper_test", _GATEKEEPER)

    def test_list_subgates(self):
        self.assertEqual(
            set(self.gk.SUB_GATES.keys()),
            {"iron-laws", "etu", "karpathy", "validator"},
        )

    def test_norm_sev_maps_to_canonical(self):
        self.assertEqual(self.gk._norm_sev("hard"), "error")
        self.assertEqual(self.gk._norm_sev("soft"), "warn")
        self.assertEqual(self.gk._norm_sev("info"), "info")
        self.assertEqual(self.gk._norm_sev("unknown"), "warn")  # safe default

    def test_verdict_with_no_findings_is_green(self):
        v = self.gk.Verdict(overall="green", findings=[], durations_ms={}, counts={})
        self.assertEqual(v.overall, "green")

    def test_render_text_includes_header_and_findings(self):
        f = self.gk.GateFinding(
            gate="etu", severity="error", rule_id="find-from-root",
            message="bad pattern", file="bad.sh", line=2,
        )
        v = self.gk.Verdict(
            overall="red", findings=[f],
            durations_ms={"etu": 5}, counts={"error": 1},
        )
        out = self.gk.render_text(v)
        self.assertIn("RED", out)
        self.assertIn("find-from-root", out)
        self.assertIn("bad.sh:2", out)

    def test_render_json_roundtrip(self):
        """render_json emits the canonical envelope (see
        assets/schemas/tool-output.schema.json) — `verdict` at top
        level, `findings` inside `data`."""
        import json
        f = self.gk.GateFinding(
            gate="iron-laws", severity="warn", rule_id="lazy-heavy-deps",
            message="msg", file="x.py",
        )
        v = self.gk.Verdict(
            overall="yellow", findings=[f],
            durations_ms={"iron-laws": 10}, counts={"warn": 1},
        )
        data = json.loads(self.gk.render_json(v))
        # Canonical envelope keys
        self.assertEqual(data["verdict"], "yellow")
        self.assertEqual(data["counts"], {"warn": 1})
        self.assertEqual(data["kaizen"]["tool"], "kaizen-gatekeeper")
        self.assertEqual(data["kaizen"]["schema_version"], 1)
        # Per-tool payload nested under `data`
        self.assertEqual(data["data"]["findings"][0]["gate"], "iron-laws")

    def test_gate_etu_returns_list(self):
        """The etu sub-gate returns a list (possibly empty), never crashes."""
        out = self.gk._gate_etu("staged", _REPO_ROOT)
        self.assertIsInstance(out, list)


class TestGatekeeperCollisionResistance(unittest.TestCase):
    """Regression — both iron-laws and efficient-tool-use ship a
    `_loader.py`; the gatekeeper must load each without collision."""

    def test_etu_loads_when_iron_laws_already_loaded(self):
        gk = _load("gatekeeper_col_test", _GATEKEEPER)
        # Force iron-laws to load first (its sys.path hack would normally
        # poison _loader for whoever loads next).
        _ = gk._gate_iron_laws("staged", _REPO_ROOT)
        # ETU should still work.
        out = gk._gate_etu("staged", _REPO_ROOT)
        # Must not return an "import-error" finding.
        for f in out:
            self.assertNotEqual(
                f.rule_id, "import-error",
                f"etu_scan failed to load post iron-laws: {f.message}",
            )


if __name__ == "__main__":
    unittest.main()
