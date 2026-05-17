"""Tests for schema_coverage — the schema/rubric conformance auditor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/schema_coverage.py"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
        env=os.environ.copy(),
    )


class TestScriptHealth(unittest.TestCase):
    def test_script_parses(self):
        with open(_SCRIPT) as f:
            compile(f.read(), str(_SCRIPT), "exec")


class TestShapeDetectors(unittest.TestCase):
    """Per-shape detection on synthetic fixtures."""

    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "schema_coverage" in sys.modules:
            del sys.modules["schema_coverage"]
        import schema_coverage as sc
        self.sc = sc
        self._tmp = tempfile.TemporaryDirectory()
        self.domain = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_lens_manifest_detected(self):
        (self.domain / "myfeat.yaml").write_text(
            "version: 2\nfeature: myfeat\nsubcommands:\n"
            "  go:\n    input_schema: schemas/in.schema.json\n"
            "    output_schema: schemas/out.schema.json\n")
        out = self.sc.detect_lens_manifest(self.domain)
        self.assertIsNotNone(out)
        self.assertTrue(out["has_input_schema"])
        self.assertTrue(out["has_output_schema"])

    def test_lens_manifest_missing_when_v1(self):
        (self.domain / "myfeat.yaml").write_text(
            "version: 1\nfeature: myfeat\nsubcommands:\n  go: {}\n")
        self.assertIsNone(self.sc.detect_lens_manifest(self.domain))

    def test_decision_rubric_detected(self):
        (self.domain / "rubric.yaml").write_text(
            "version: 1\nrules:\n  - bucket: x\n    require_all:\n"
            "      - {signal: foo, op: '>=', value: 1}\n")
        out = self.sc.detect_decision_rubric(self.domain)
        self.assertIsNotNone(out)
        self.assertTrue(out["has_require"])

    def test_plain_config_detected(self):
        (self.domain / "config.yaml").write_text("version: 1\nkey: value\n")
        out = self.sc.detect_plain_config(self.domain)
        self.assertIsNotNone(out)

    def test_plain_config_missing_without_version(self):
        (self.domain / "config.yaml").write_text("key: value\n")
        self.assertIsNone(self.sc.detect_plain_config(self.domain))

    def test_rule_catalog_detected(self):
        (self.domain / "intents.yaml").write_text(
            "version: 1\nintents:\n  - id: wrap-up\n    pattern: x\n")
        out = self.sc.detect_rule_catalog(self.domain)
        self.assertIsNotNone(out)


class TestFeatureReport(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        if "schema_coverage" in sys.modules:
            del sys.modules["schema_coverage"]
        import schema_coverage as sc
        self.sc = sc
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_domain_is_not_conformant_but_no_gaps(self):
        feat = self.root / "x"; feat.mkdir()
        (feat / "SKILL.md").write_text("body")
        r = self.sc.feature_report(feat)
        self.assertFalse(r["has_domain"])
        self.assertEqual(r["matched_shapes"], [])
        self.assertEqual(r["gaps"], [])  # no domain = no shape-expectations
        self.assertFalse(r["conformant"])

    def test_domain_with_no_shape_match_flagged(self):
        feat = self.root / "x"; feat.mkdir()
        (feat / "domain").mkdir()
        (feat / "domain/some.yaml").write_text("free: form\n")
        r = self.sc.feature_report(feat)
        self.assertTrue(r["has_domain"])
        self.assertEqual(r["matched_shapes"], [])
        self.assertTrue(any("no-shape" in g for g in r["gaps"]))

    def test_conformant_feature_passes(self):
        feat = self.root / "good"; feat.mkdir()
        (feat / "domain").mkdir()
        (feat / "domain/schemas").mkdir()
        (feat / "domain/config.yaml").write_text("version: 1\n")
        (feat / "domain/schemas/x.schema.json").write_text("{}")
        r = self.sc.feature_report(feat)
        self.assertTrue(r["conformant"])
        self.assertIn("plain-config", r["matched_shapes"])


class TestRealPluginReport(unittest.TestCase):
    def test_report_runs_against_real_plugin(self):
        r = _run("report")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("schema-coverage:", r.stdout)

    def test_report_json_shape(self):
        r = _run("report", "--json")
        data = json.loads(r.stdout)
        self.assertGreater(len(data), 10)
        for entry in data[:3]:
            for k in ("feature", "has_domain", "yamls", "schemas",
                       "matched_shapes", "gaps", "conformant"):
                self.assertIn(k, entry)

    def test_token_bloat_is_conformant(self):
        """We built token-bloat following the canonical shape — it
        should pass conformance (decision-rubric for split-rubric.yaml
        + schemas)."""
        r = _run("feature", "token-bloat", "--json")
        data = json.loads(r.stdout)
        self.assertTrue(data["conformant"],
                          f"token-bloat not conformant: {data['gaps']}")
        self.assertIn("decision-rubric", data["matched_shapes"])

    def test_feature_unknown_exits_1(self):
        r = _run("feature", "no-such-feature-12345")
        self.assertEqual(r.returncode, 1)

    def test_gaps_subcommand_exit_codes(self):
        """gaps subcommand exits 1 when any feature has gaps (CI gate)."""
        r = _run("gaps")
        # Real plugin has known gaps (brain, code-tour, etc.) → exit 1
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
