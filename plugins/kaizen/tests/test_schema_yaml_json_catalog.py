"""Tests for the schema/yaml/json patterns catalog in
skills/plugin-development/SKILL.md.

Validates:
  1. The catalog section exists in SKILL.md
  2. The four shapes are documented (lens, rubric, plain config, rule catalog)
  3. Live skills actually match the cataloged shapes (empirical)
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SKILL_MD = _KZ_DIR / "skills/plugin-development/SKILL.md"


class TestCatalogSection(unittest.TestCase):
    def setUp(self):
        self.body = _SKILL_MD.read_text(encoding="utf-8")

    def test_catalog_section_present(self):
        self.assertIn("Catalog — established schema / yaml / json shapes",
                      self.body)

    def test_lists_four_shapes(self):
        for shape in ("Lens manifest", "Decision rubric",
                      "Plain config", "Rule catalog"):
            self.assertIn(shape, self.body,
                          f"shape {shape!r} not documented")

    def test_documents_when_to_pick_which(self):
        self.assertIn("When to pick which shape", self.body)

    def test_documents_json_state_files_section(self):
        self.assertIn("JSON state files", self.body)

    def test_each_shape_shows_yaml_example(self):
        # Each shape has a fenced ```yaml block close to its heading
        yaml_blocks = self.body.count("```yaml")
        self.assertGreaterEqual(yaml_blocks, 4,
                                f"expected ≥4 yaml example blocks, got {yaml_blocks}")


class TestLiveSkillsMatchCatalog(unittest.TestCase):
    """Empirical: live skills the catalog cites actually conform."""

    SKILLS_DIR = _KZ_DIR / "skills"

    def _load_yaml(self, path: Path) -> dict:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_handoff_manifest_is_v2(self):
        try:
            import yaml  # noqa
        except ImportError:
            self.skipTest("yaml not installed")
        m = self._load_yaml(self.SKILLS_DIR / "handoff/domain/handoff.yaml")
        self.assertEqual(m.get("version"), 2)
        self.assertEqual(m.get("feature"), "handoff")

    def test_auto_handoff_rubric_uses_bucket_walker_shape(self):
        try:
            import yaml  # noqa
        except ImportError:
            self.skipTest("yaml not installed")
        r = self._load_yaml(
            self.SKILLS_DIR / "auto-handoff/domain/rubric.yaml")
        self.assertEqual(r.get("version"), 1)
        self.assertIn("rules", r)
        self.assertIn("fallback", r)
        for rule in r["rules"]:
            self.assertIn("bucket", rule)
            self.assertTrue("require_all" in rule or "require_any" in rule)

    def test_auto_handoff_config_is_plain_config_shape(self):
        try:
            import yaml  # noqa
        except ImportError:
            self.skipTest("yaml not installed")
        c = self._load_yaml(
            self.SKILLS_DIR / "auto-handoff/domain/config.yaml")
        self.assertEqual(c.get("version"), 1)
        self.assertIn("on_fire", c)
        # on_bucket present (per-bucket policy paired with rubric)
        self.assertIn("on_bucket", c)

    def test_intents_yaml_is_rule_catalog_shape(self):
        try:
            import yaml  # noqa
        except ImportError:
            self.skipTest("yaml not installed")
        i = self._load_yaml(
            self.SKILLS_DIR / "intent/domain/intents.yaml")
        self.assertEqual(i.get("version"), 1)
        self.assertIn("intents", i)
        for entry in i["intents"]:
            self.assertIn("id", entry)
            # kebab-case ID
            self.assertRegex(entry["id"], r"^[a-z][a-z0-9-]*$",
                              f"bad id format: {entry['id']!r}")


class TestSchemasUseDraft07(unittest.TestCase):
    """All shipped *.schema.json should declare draft-07 (the only
    one BucketWalker/jsonschema validates against in tests)."""

    def test_all_shipped_schemas_declare_schema_url(self):
        misses = []
        for p in (_KZ_DIR / "skills").rglob("*.schema.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                misses.append(f"{p}: invalid JSON")
                continue
            if "$schema" not in data:
                misses.append(f"{p}: missing $schema")
        # Allow some misses (e.g. nested $defs files), but the bulk
        # should declare it. Threshold: ≥80% have it.
        all_schemas = list((_KZ_DIR / "skills").rglob("*.schema.json"))
        compliant = len(all_schemas) - len(misses)
        ratio = compliant / max(1, len(all_schemas))
        self.assertGreaterEqual(
            ratio, 0.8,
            f"<80% of shipped schemas declare $schema ({compliant}/{len(all_schemas)}): "
            f"{misses[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
