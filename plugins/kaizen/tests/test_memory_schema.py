"""Phase E: schema validation for Note / memory-entry frontmatter.

Single declarative schema at
``schemas/brain/schemas/memory-entry.schema.json`` validates
brain Notes, brain Inbox drafts, and project-memory entries — all
share the same frontmatter shape.

Pure validator: ``memory_schema.validate(frontmatter_dict) → list[error]``.
Composes with the existing _yaml_safe writer (Phase 8) so writes are
both YAML-safe AND schema-conformant. Schema-violations surface
through the brain-drift gate as a new rule_id (next session).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
class TestSchemaFileExists(unittest.TestCase):
    """The schema must exist at the canonical location + be valid JSON."""

    def test_schema_file_is_valid_json(self):
        schema_path = (ROOT / "schemas" / "brain" /
                       "schemas" / "memory-entry.schema.json")
        self.assertTrue(schema_path.is_file(),
                         f"schema missing at {schema_path}")
        data = json.loads(schema_path.read_text())
        # Minimal JSON Schema sanity
        self.assertIn("$schema", data)
        self.assertEqual(data.get("type"), "object")

class TestValidate(unittest.TestCase):
    """`memory_schema.validate(frontmatter_dict)` returns a list of
    error strings (empty == valid)."""

    def test_well_formed_entry_passes(self):
        import memory_schema
        errors = memory_schema.validate({
            "name": "X",
            "description": "Y",
            "type": "world-fact",
            "tags": [],
        })
        self.assertEqual(errors, [])

    def test_minimal_required_passes(self):
        """Only name + description are strictly required."""
        import memory_schema
        errors = memory_schema.validate({"name": "A", "description": "B"})
        self.assertEqual(errors, [])

    def test_missing_name_fails(self):
        import memory_schema
        errors = memory_schema.validate({"description": "no name"})
        self.assertTrue(errors)
        self.assertTrue(any("name" in e.lower() for e in errors))

    def test_invalid_type_value_fails(self):
        import memory_schema
        errors = memory_schema.validate({
            "name": "X", "description": "Y", "type": "not-a-real-type"})
        self.assertTrue(errors)
        self.assertTrue(any("type" in e.lower() for e in errors))

    def test_tags_must_be_list(self):
        import memory_schema
        errors = memory_schema.validate({
            "name": "X", "description": "Y", "tags": "not-a-list"})
        self.assertTrue(errors)

    def test_confidence_must_be_in_0_to_1(self):
        import memory_schema
        # Above 1.0
        errors_hi = memory_schema.validate({
            "name": "X", "description": "Y", "confidence": 1.5})
        self.assertTrue(errors_hi)
        # Below 0
        errors_lo = memory_schema.validate({
            "name": "X", "description": "Y", "confidence": -0.1})
        self.assertTrue(errors_lo)
        # In range
        errors_ok = memory_schema.validate({
            "name": "X", "description": "Y", "confidence": 0.5})
        self.assertEqual(errors_ok, [])

class TestValidateText(unittest.TestCase):
    """`validate_text(file_text)` parses the YAML frontmatter + validates."""

    def test_validates_full_md_file(self):
        import memory_schema
        text = ("---\nname: X\ndescription: Y\ntype: world-fact\n---\n\n"
                "body content\n")
        errors = memory_schema.validate_text(text)
        self.assertEqual(errors, [])

    def test_missing_frontmatter_returns_error(self):
        import memory_schema
        errors = memory_schema.validate_text("no frontmatter here\n")
        self.assertTrue(errors)
        self.assertTrue(any("frontmatter" in e.lower() for e in errors))

    def test_malformed_yaml_returns_error(self):
        import memory_schema
        text = "---\nname: 'unterminated\n---\n"
        errors = memory_schema.validate_text(text)
        self.assertTrue(errors)

if __name__ == "__main__":
    unittest.main()
