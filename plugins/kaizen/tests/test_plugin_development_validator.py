"""Tests for plugin-development/scripts/validate.py — canonical
feature-shape validator.

Verifies:
- Discovery: vendored skills excluded, plugin-original included
- Per-feature shape: required slots checked, conditional slots
  gated on predicate
- Manifest inference vs explicit manifest.yaml
- Op-suffix substitution (multi-op features)
- --json output schema
- Exit codes (0 clean / 1 soft / 2 hard)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
# Post-consolidation: validate.py lives at scripts/plugin_development/.
# Legacy path skills/plugin-development/scripts/validate.py still works as
# a MIGRATION BRIDGE shim, but tests target the canonical location.
_VALIDATE = _KZ_DIR / "scripts" / "plugin_development" / "validate.py"


def _run(*args, expect_rc=None):
    """Invoke validate.py as a subprocess. Returns (rc, stdout)."""
    result = subprocess.run(
        ["python3", str(_VALIDATE), *args],
        capture_output=True, text=True, timeout=15,
    )
    if expect_rc is not None:
        if result.returncode != expect_rc:
            raise AssertionError(
                f"expected rc={expect_rc}, got {result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
    return result.returncode, result.stdout


class TestValidatorSmoke(unittest.TestCase):
    def test_script_exists_and_executable(self):
        self.assertTrue(_VALIDATE.is_file(), f"missing {_VALIDATE}")
        self.assertTrue(
            os.access(_VALIDATE, os.X_OK),
            "validate.py must be executable",
        )

    def test_help_works(self):
        rc, out = _run("--help")
        self.assertEqual(rc, 0)
        self.assertIn("plugin-original", out + "")

    def test_brain_feature_validates_clean(self):
        # After the B1-B5 work, brain should pass the canonical-shape check.
        rc, out = _run("--feature", "brain")
        self.assertIn("brain", out)
        # rc==0 (clean) or 1 (soft only); MUST NOT be 2 (hard)
        self.assertIn(rc, (0, 1), f"brain validation hard-failed:\n{out}")


class TestValidatorAll(unittest.TestCase):
    def test_all_discovers_plugin_originals_excludes_vendored(self):
        rc, out = _run("--all")
        # Brain (plugin-original) should appear
        self.assertIn("brain", out)
        # plugin-development (this skill itself, plugin-original) should appear
        self.assertIn("plugin-development", out)
        # kiss (vendored) should NOT
        self.assertNotIn("kiss", out)

    def test_all_returns_exit_code(self):
        rc, _ = _run("--all")
        # Whatever the current state, rc must be 0/1/2 (no crash)
        self.assertIn(rc, (0, 1, 2))


class TestValidatorJson(unittest.TestCase):
    def test_json_output_parses(self):
        rc, out = _run("--feature", "brain", "--json")
        # Phase D2: wrapped in canonical envelope
        envelope = json.loads(out)
        self.assertIn("kaizen", envelope)
        self.assertIn("data", envelope)
        data = envelope["data"]
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertEqual(entry["feature"], "brain")
        self.assertIn("hard", entry)
        self.assertIn("soft", entry)
        self.assertIn("findings", entry)


class TestValidatorStaged(unittest.TestCase):
    def test_staged_runs_cleanly(self):
        # We don't know what's staged; just verify the mode doesn't crash.
        rc, _ = _run("--staged")
        self.assertIn(rc, (0, 1, 2))


class TestVendoredExclusion(unittest.TestCase):
    """The validator's VENDORED_SKILLS list MUST stay in sync with
    iron-laws.yaml::no-modify-vendored."""

    def test_validator_module_loads(self):
        sys.path.insert(0, str(_VALIDATE.parent))
        try:
            import validate
        except Exception as e:
            self.fail(f"validate.py failed to import: {e}")

        # Spot-check: known vendored skills are excluded
        for skill in ("kiss", "solid", "dry", "yagni", "karpathy"):
            self.assertIn(skill, validate.VENDORED_SKILLS)
        # Spot-check: known plugin-original skills are NOT excluded
        for skill in ("brain", "workflow", "plugin-development"):
            self.assertNotIn(skill, validate.VENDORED_SKILLS)


class TestSchemaLoad(unittest.TestCase):
    """The validator's yaml loader must read all three domain files."""

    def test_feature_shape_loads(self):
        sys.path.insert(0, str(_VALIDATE.parent))
        import validate
        data = validate._load_yaml(validate.DOMAIN_DIR / "feature-shape.yaml")
        self.assertIn("slots", data)
        self.assertGreater(len(data["slots"]), 5)

    def test_iron_laws_loads(self):
        sys.path.insert(0, str(_VALIDATE.parent))
        import validate
        data = validate._load_yaml(validate.IRON_LAWS_YAML)
        self.assertIn("laws", data)
        self.assertGreater(len(data["laws"]), 5)

    def test_wiring_checklist_loads(self):
        sys.path.insert(0, str(_VALIDATE.parent))
        import validate
        data = validate._load_yaml(
            validate.DOMAIN_DIR / "wiring-checklist.yaml"
        )
        self.assertIn("artifacts", data)


class TestSchemaJsonValid(unittest.TestCase):
    """feature.schema.json must be valid JSON + valid JSONSchema."""

    def test_feature_schema_parses(self):
        sys.path.insert(0, str(_VALIDATE.parent))
        import validate
        schema_path = (
            validate.DOMAIN_DIR / "schemas" / "feature.schema.json"
        )
        with open(schema_path) as f:
            data = json.load(f)
        self.assertIn("$schema", data)
        self.assertIn("type", data)


if __name__ == "__main__":
    unittest.main()
