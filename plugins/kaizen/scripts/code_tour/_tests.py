#!/usr/bin/env python3
"""TDD: tests written BEFORE the yaml + schema land.

Run: python3 _tests.py
Expected: FAIL on first run (RED). Then write the yaml + schema. Tests pass (GREEN).
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


class TestPersonas(unittest.TestCase):
    def setUp(self):
        self.path = DOMAIN / "personas.yaml"
        self.schema_path = DOMAIN / "schemas" / "persona.schema.json"

    def test_yaml_exists(self):
        self.assertTrue(self.path.exists(), f"missing: {self.path}")

    def test_schema_exists(self):
        self.assertTrue(self.schema_path.exists(), f"missing: {self.schema_path}")

    def test_has_10_personas(self):
        data = yaml.safe_load(self.path.read_text())
        self.assertEqual(len(data["personas"]), 10)

    def test_exactly_one_default_persona(self):
        data = yaml.safe_load(self.path.read_text())
        defaults = [p for p in data["personas"] if p.get("is_default")]
        self.assertEqual(len(defaults), 1, "exactly one persona must be is_default: true")
        self.assertEqual(defaults[0]["id"], "new-joiner")

    def test_all_personas_have_required_fields(self):
        data = yaml.safe_load(self.path.read_text())
        for p in data["personas"]:
            for key in ["id", "goal", "must_cover", "default_depth"]:
                self.assertIn(key, p, f"persona {p.get('id', '?')} missing {key}")

    def test_default_depths_are_valid(self):
        data = yaml.safe_load(self.path.read_text())
        valid = {"quick", "standard", "deep"}
        for p in data["personas"]:
            self.assertIn(p["default_depth"], valid, f"{p['id']}: bad depth {p['default_depth']}")

    def test_schema_validates(self):
        if not _HAS_JSONSCHEMA:
            self.skipTest("jsonschema not installed")
        data = yaml.safe_load(self.path.read_text())
        schema = json.loads(self.schema_path.read_text())
        validate(data, schema)


class TestDepths(unittest.TestCase):
    def setUp(self):
        self.path = DOMAIN / "depths.yaml"
        self.schema_path = DOMAIN / "schemas" / "depth.schema.json"

    def test_yaml_exists(self):
        self.assertTrue(self.path.exists(), f"missing: {self.path}")

    def test_has_three_depths(self):
        data = yaml.safe_load(self.path.read_text())
        self.assertEqual(set(data["depths"].keys()), {"quick", "standard", "deep"})

    def test_step_count_ranges(self):
        data = yaml.safe_load(self.path.read_text())
        # Upstream-faithful counts
        self.assertEqual(data["depths"]["quick"]["min_steps"], 5)
        self.assertEqual(data["depths"]["quick"]["max_steps"], 8)
        self.assertEqual(data["depths"]["standard"]["min_steps"], 9)
        self.assertEqual(data["depths"]["standard"]["max_steps"], 13)
        self.assertEqual(data["depths"]["deep"]["min_steps"], 14)
        self.assertEqual(data["depths"]["deep"]["max_steps"], 18)

    def test_min_lte_max(self):
        data = yaml.safe_load(self.path.read_text())
        for name, depth in data["depths"].items():
            self.assertLessEqual(depth["min_steps"], depth["max_steps"], f"{name}: min > max")

    def test_schema_validates(self):
        if not _HAS_JSONSCHEMA or not self.schema_path.exists():
            self.skipTest("schema not present yet")
        data = yaml.safe_load(self.path.read_text())
        schema = json.loads(self.schema_path.read_text())
        validate(data, schema)


class TestStepTypes(unittest.TestCase):
    def setUp(self):
        self.path = DOMAIN / "step-types.yaml"

    def test_yaml_exists(self):
        self.assertTrue(self.path.exists(), f"missing: {self.path}")

    def test_has_six_step_types(self):
        data = yaml.safe_load(self.path.read_text())
        ids = {s["id"] for s in data["step_types"]}
        self.assertEqual(ids, {"content", "directory", "file_line", "selection", "pattern", "uri"})

    def test_max_content_step_count(self):
        data = yaml.safe_load(self.path.read_text())
        content = next(s for s in data["step_types"] if s["id"] == "content")
        self.assertEqual(content.get("max_per_tour"), 2,
                         "content steps capped at 2 per tour (upstream rule)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
