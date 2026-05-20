"""Unit tests for the `shim-and-sweep` routine (extracted from
shodan's borg-loop discipline).

Locks the wire-up:
  - schemas/shim-and-sweep/schema.yaml exists + parses + validates
  - skills/shim-and-sweep/SKILL.md exists + has proper frontmatter
  - domain/routines.yaml declares the routine + maps schema_path
  - Phase list matches between schema artifacts + routine stages
  - Trigger words include the canonical aliases ("carve", "borg-loop",
    "deferred deletion", "F-FINAL", etc.)

Run:
    python3 -m unittest tests.test_shim_and_sweep -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

SCHEMA = PLUGIN_ROOT / "schemas" / "shim-and-sweep" / "schema.yaml"
SKILL = PLUGIN_ROOT / "skills" / "shim-and-sweep" / "SKILL.md"
ROUTINES = PLUGIN_ROOT / "schemas" / "workflow" / "routines.yaml"
WORKFLOW_JSON_SCHEMA = PLUGIN_ROOT / "assets" / "schemas" / "workflow.schema.json"


class TestSchemaFile(unittest.TestCase):
    """The yaml schema declaring the 10-phase routine."""

    @classmethod
    def setUpClass(cls):
        cls.schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))

    def test_schema_exists(self):
        self.assertTrue(SCHEMA.is_file(), f"missing {SCHEMA}")

    def test_name_and_version(self):
        self.assertEqual(self.schema["name"], "shim-and-sweep")
        self.assertEqual(self.schema["version"], 1)

    def test_validates_against_workflow_json_schema(self):
        try:
            from jsonschema import validate
        except ImportError:
            self.skipTest("jsonschema not installed")
        if not WORKFLOW_JSON_SCHEMA.is_file():
            self.skipTest("workflow.schema.json missing")
        validate(self.schema, json.loads(WORKFLOW_JSON_SCHEMA.read_text()))

    def test_artifact_phases_locked(self):
        """The 10-phase ordering is the contract — drift here is a
        behavior change."""
        ids = [a["id"] for a in self.schema["artifacts"]]
        self.assertEqual(ids, [
            "explore",
            "analyze",
            "characterize",
            "create-plan",
            "create-tasks",
            "carve-with-shim",
            "migrate-callers",
            "drift-check",
            "sweep",
            "validate",
        ])

    def test_characterize_is_the_gate(self):
        self.assertEqual(self.schema["apply"]["gate"], "characterize")

    def test_carve_phase_describes_shim_discipline(self):
        carve = next(a for a in self.schema["artifacts"] if a["id"] == "carve-with-shim")
        body = carve["description"]
        # Shim creation must be explicit + the manifest must be touched.
        self.assertIn("shim", body.lower())
        self.assertIn("manifest", body.lower())
        # No mid-refactor git rm.
        self.assertIn("git rm", body)

    def test_sweep_phase_is_user_gated(self):
        sweep = next(a for a in self.schema["artifacts"] if a["id"] == "sweep")
        body = sweep["description"]
        self.assertIn("KAIZEN_ALLOW_DELETE", body)
        self.assertIn("pre-sweep-", body)  # safety tag pattern
        # Pre-conditions block must mention the drift-check + user auth.
        self.assertIn("Pre-conditions", body)


class TestSkillFile(unittest.TestCase):
    """The SKILL.md companion."""

    @classmethod
    def setUpClass(cls):
        cls.text = SKILL.read_text(encoding="utf-8")

    def test_skill_exists(self):
        self.assertTrue(SKILL.is_file(), f"missing {SKILL}")

    def test_frontmatter_name_and_description(self):
        self.assertTrue(self.text.startswith("---\n"))
        # Split frontmatter
        _, fm, _ = self.text.split("---\n", 2)
        data = yaml.safe_load(fm)
        self.assertEqual(data["name"], "shim-and-sweep")
        self.assertIn("description", data)
        # Trigger phrases must include the canonical aliases so the
        # description routes Claude Code's skill dispatch correctly.
        desc = data["description"].lower()
        for phrase in ("borg-loop", "carve out", "deletion manifest", "f-final", "shim"):
            self.assertIn(phrase.lower(), desc, f"missing trigger: {phrase}")

    def test_iron_laws_section_present(self):
        # The 5 iron laws are the load-bearing discipline; missing
        # section is a major content regression.
        self.assertIn("## Iron Laws", self.text)
        # Each of the 5 laws references the key concept.
        for keyword in ("git rm", "Compile", "manifest", "F-FINAL", "safety tag"):
            self.assertIn(keyword, self.text, f"Iron Laws missing concept: {keyword}")

    def test_pre_commit_gate_interaction_documented(self):
        # The skill must explain how it cooperates with the existing
        # pre_deletion_belief gate.
        self.assertIn("pre_deletion_belief", self.text)
        self.assertIn("KAIZEN_ALLOW_DELETE", self.text)

    def test_shim_shapes_table_present(self):
        # Without per-language shim guidance the routine isn't actionable.
        for lang in ("Rust", "Python", "TypeScript"):
            self.assertIn(lang, self.text, f"shim shape missing for {lang}")


class TestRoutinesWireup(unittest.TestCase):
    """domain/routines.yaml must declare the routine + point at the schema."""

    @classmethod
    def setUpClass(cls):
        cls.data = yaml.safe_load(ROUTINES.read_text(encoding="utf-8"))
        cls.entry = next(
            (r for r in cls.data["routines"] if r["name"] == "shim-and-sweep"),
            None,
        )

    def test_routine_declared(self):
        self.assertIsNotNone(self.entry, "shim-and-sweep routine missing from routines.yaml")

    def test_routine_points_at_schema_file(self):
        self.assertEqual(self.entry["schema_path"], "schemas/shim-and-sweep/schema.yaml")

    def test_routine_stages_match_schema_artifacts(self):
        schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
        schema_ids = [a["id"] for a in schema["artifacts"]]
        self.assertEqual(self.entry["stages"], schema_ids,
                         "routine.stages must mirror schema.artifacts[*].id verbatim")

    def test_trigger_words_cover_canonical_aliases(self):
        triggers = " | ".join(self.entry["trigger_words"]).lower()
        for alias in ("carve", "borg-loop", "shim", "deletion manifest", "f-final"):
            self.assertIn(alias.lower(), triggers,
                          f"trigger_words missing alias: {alias}")

    def test_routine_uses_schema_kind(self):
        # `kind: schema` makes the workflow runner load the yaml; `hardcoded`
        # would expect inline-only routines.
        self.assertEqual(self.entry["kind"], "schema")


if __name__ == "__main__":
    unittest.main()
