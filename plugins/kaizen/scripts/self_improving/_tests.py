#!/usr/bin/env python3
"""TDD: tests written BEFORE the lifecycle.yaml + schema land. RED → GREEN.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOMAIN = SCRIPT_DIR.parent / "domain"

try:
    import yaml
except ImportError:
    sys.stderr.write("pyyaml required\n")
    sys.exit(1)

try:
    from jsonschema import validate
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.path = DOMAIN / "lifecycle.yaml"
        self.schema_path = DOMAIN / "schemas" / "lifecycle.schema.json"

    def test_yaml_exists(self):
        self.assertTrue(self.path.exists())

    def test_schema_exists(self):
        self.assertTrue(self.schema_path.exists())

    def test_has_five_stages(self):
        data = yaml.safe_load(self.path.read_text())
        ids = [s["id"] for s in data["lifecycle"]]
        self.assertEqual(ids, ["discover", "recurs", "approve", "graduate", "archive"])

    def test_recurs_threshold_is_two_sessions(self):
        data = yaml.safe_load(self.path.read_text())
        recurs = next(s for s in data["lifecycle"] if s["id"] == "recurs")
        self.assertEqual(recurs["threshold"], "2_sessions")

    def test_graduate_has_routing_table(self):
        data = yaml.safe_load(self.path.read_text())
        graduate = next(s for s in data["lifecycle"] if s["id"] == "graduate")
        self.assertIn("routing_table", graduate)
        rt = graduate["routing_table"]
        # Must cover the 4 destination categories
        for key in ["project_correction", "project_scoped_rule",
                    "cross_project_belief", "enforceable_rule"]:
            self.assertIn(key, rt, f"routing missing {key}")

    def test_sub_flows_present(self):
        data = yaml.safe_load(self.path.read_text())
        ids = {f["id"] for f in data["sub_flows"]}
        # remember + status delegate to existing kaizen skills, not duplicated here
        self.assertEqual(ids, {"review", "promote", "extract"})

    def test_extract_requires_three_recurrences(self):
        data = yaml.safe_load(self.path.read_text())
        extract = next(f for f in data["sub_flows"] if f["id"] == "extract")
        self.assertEqual(extract["requires"], ["pattern_recurs_3x"])

    def test_schema_validates(self):
        if not _HAS_JSONSCHEMA:
            self.skipTest("jsonschema not installed")
        data = yaml.safe_load(self.path.read_text())
        schema = json.loads(self.schema_path.read_text())
        validate(data, schema)

if __name__ == "__main__":
    unittest.main(verbosity=2)
