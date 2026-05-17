"""RED first — kaizen.toml JSON Schema + Taplo integration tests.

Validates:
  - assets/schemas/kaizen-config.schema.json exists + is valid
    JSON Schema 2020-12
  - schema accepts the canonical seeded .kaizen.toml
  - schema rejects garbage (wrong types)
  - every key written by setup.sh's heredoc is covered by the schema
  - plugin-root taplo.toml exists + maps the schema to **/.kaizen.toml
  - setup.sh heredoc starts the seeded file with a `#:schema`
    directive so Taplo / Even Better TOML / IDE LSPs auto-bind

Run:
    python3 -m unittest tests.test_kaizen_config_schema -v
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PLUGIN_ROOT / "assets" / "schemas" / "kaizen-config.schema.json"
TAPLO_PATH  = PLUGIN_ROOT / "taplo.toml"
SETUP_SH    = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "setup.sh"


# ─── Schema file exists + parseable ────────────────────────────────────

class SchemaFile(unittest.TestCase):

    def test_schema_file_exists(self):
        self.assertTrue(SCHEMA_PATH.exists(),
                         f"missing: {SCHEMA_PATH}")

    def test_schema_parses_as_json(self):
        json.loads(SCHEMA_PATH.read_text())

    def test_schema_declares_2020_12_draft(self):
        s = json.loads(SCHEMA_PATH.read_text())
        self.assertIn("json-schema.org/draft/2020-12", s.get("$schema", ""),
                        "must declare 2020-12 draft for Taplo compat")

    def test_schema_has_id_and_title(self):
        s = json.loads(SCHEMA_PATH.read_text())
        self.assertTrue(s.get("$id"), "must have $id (referenced from #:schema)")
        self.assertTrue(s.get("title"), "must have a title")

    def test_schema_forbids_additional_properties(self):
        """Strict — surface typos at edit time."""
        s = json.loads(SCHEMA_PATH.read_text())
        self.assertFalse(s.get("additionalProperties", True),
                            "additionalProperties must be false")


# ─── Schema content covers every key setup.sh writes ─────────────────

EXPECTED_KEYS = {
    "compile_check_cmd",
    "architecture_log",
    "plan_dir",
    "backlog_path",
    "verify_cmd",
    "allow_deletion_env",
    "skip_tdd_check_env",
    "brain_path",
    "project_memory_path",
}


class SchemaCoverage(unittest.TestCase):

    def test_every_seeded_key_is_in_schema_properties(self):
        s = json.loads(SCHEMA_PATH.read_text())
        props = set(s.get("properties", {}).keys())
        missing = EXPECTED_KEYS - props
        self.assertEqual(missing, set(),
                            f"schema missing keys: {missing}")

    def test_path_typed_keys_have_string_type(self):
        s = json.loads(SCHEMA_PATH.read_text())
        for key in ("architecture_log", "plan_dir", "backlog_path",
                     "brain_path", "project_memory_path"):
            p = s["properties"][key]
            self.assertEqual(p.get("type"), "string",
                                f"{key}: type must be string")

    def test_env_var_keys_pattern_validated(self):
        """allow_deletion_env / skip_tdd_check_env are env-var NAMES —
        should be A-Z + underscore + digits only."""
        s = json.loads(SCHEMA_PATH.read_text())
        for key in ("allow_deletion_env", "skip_tdd_check_env"):
            p = s["properties"][key]
            self.assertIn("pattern", p,
                            f"{key} should have a pattern for env-var names")
            # pattern itself should accept "KAIZEN_ALLOW_DELETE" + reject "lowercase"
            pat = re.compile(p["pattern"])
            self.assertTrue(pat.fullmatch("KAIZEN_ALLOW_DELETE"))
            self.assertFalse(pat.fullmatch("lowercase-name"))


# ─── jsonschema accepts the canonical good config, rejects bad ────────

GOOD = {
    "compile_check_cmd": "ruff check .",
    "architecture_log":  ".kaizen/workflow/progress.md",
    "plan_dir":          "plans",
    "backlog_path":      ".kaizen/workflow/backlog.md",
    "verify_cmd":        "",
    "allow_deletion_env": "KAIZEN_ALLOW_DELETE",
    "skip_tdd_check_env": "KAIZEN_SKIP_TDD_CHECK",
    "brain_path":        "/home/me/.claude/brain",
    "project_memory_path": "/home/me/.claude/projects/x/memory",
}


class SchemaValidates(unittest.TestCase):

    def setUp(self):
        try:
            import jsonschema   # noqa: F401
        except ImportError:
            self.skipTest("jsonschema not installed in test env")

    def test_good_config_validates(self):
        import jsonschema
        s = json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(GOOD, s)

    def test_extra_key_rejected(self):
        import jsonschema
        s = json.loads(SCHEMA_PATH.read_text())
        bad = dict(GOOD, bogus_key="nope")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, s)

    def test_wrong_type_rejected(self):
        import jsonschema
        s = json.loads(SCHEMA_PATH.read_text())
        bad = dict(GOOD, plan_dir=42)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, s)

    def test_bad_env_var_name_rejected(self):
        import jsonschema
        s = json.loads(SCHEMA_PATH.read_text())
        bad = dict(GOOD, allow_deletion_env="lowercase!name")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, s)


# ─── Taplo project mapping ─────────────────────────────────────────────

class TaploConfig(unittest.TestCase):

    def test_taplo_toml_exists_in_plugin_root(self):
        self.assertTrue(TAPLO_PATH.exists(), f"missing: {TAPLO_PATH}")

    def test_taplo_toml_maps_schema_to_kaizen_toml(self):
        body = TAPLO_PATH.read_text()
        # Must reference the schema by relative path or URL
        self.assertTrue(
            "kaizen-config.schema.json" in body,
            "taplo.toml must reference kaizen-config.schema.json",
        )
        # Must map to .kaizen.toml glob
        self.assertTrue(
            ".kaizen.toml" in body or "kaizen.toml" in body,
            "taplo.toml must map the schema to **/.kaizen.toml",
        )

    def test_taplo_toml_has_schema_block(self):
        body = TAPLO_PATH.read_text()
        self.assertIn("[[schema]]", body,
                         "taplo.toml needs a [[schema]] section for the binding")


# ─── setup.sh heredoc emits #:schema directive ────────────────────────

class SetupHeredoc(unittest.TestCase):

    def test_setup_sh_heredoc_starts_with_schema_directive(self):
        """The seeded .kaizen.toml must lead with a `#:schema ...` line
        so editors (Taplo / Even Better TOML) auto-bind without needing
        the project-level taplo.toml — useful when this repo's plugin
        isn't installed yet."""
        body = SETUP_SH.read_text()
        # Find the kaizen.toml heredoc block
        m = re.search(r'cat\s*>\s*"\$CONFIG_PATH"\s*<<TOML\s*\n(.*?)\nTOML',
                        body, re.DOTALL)
        self.assertIsNotNone(m, "setup.sh has no `cat > $CONFIG_PATH <<TOML` block")
        heredoc = m.group(1)
        # First non-empty, non-comment-banner line should be the #:schema directive
        # (we allow the existing first-line "# kaizen config — generated …" banner)
        self.assertIn("#:schema", heredoc,
                         "heredoc must include a `#:schema` directive")
        # Directive should reference the schema
        self.assertIn("kaizen-config.schema.json", heredoc,
                         "#:schema must reference kaizen-config.schema.json")


if __name__ == "__main__":
    unittest.main()
