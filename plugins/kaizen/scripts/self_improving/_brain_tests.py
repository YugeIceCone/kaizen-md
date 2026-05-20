#!/usr/bin/env python3
"""TDD: brain-automation tests. RED → GREEN.

Tests:
  1. Notes frontmatter JSON Schema exists + validates real Notes
  2. brain_validator.py exists + reports cleanly on the live brain
  3. brain_codegen.py exists + regenerates Persona Top Beliefs from Notes
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = SCRIPT_DIR.parent.parent
DOMAIN = _PLUGIN_ROOT / "skills" / "self-improving" / "domain"
# Post-flatten: brain_codegen.py + brain_validator.py live alongside this file
# (no nested brain/ subdir). BRAIN_TOOLS unused now — kept for API compat.
BRAIN_TOOLS = SCRIPT_DIR
# Canonical note schema lives in the brain skill (not self-improving) — single
# source of truth for <KAIZEN_BRAIN_DIR>/Notes/*.md frontmatter.
BRAIN_SCHEMA_DOMAIN = _PLUGIN_ROOT / "skills" / "brain" / "domain"

# Resolve brain root via the kaizen SSOT (v1.38.0+). KAIZEN_BRAIN_DIR
# is the only env that resolves; default ~/.claude/.kaizen/brain.
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts" / "io"))
import _paths  # noqa: E402
BRAIN = _paths.BRAIN_DIR

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


def _coerce_dates(d):
    import datetime as _dt
    if isinstance(d, dict): return {k: _coerce_dates(v) for k, v in d.items()}
    if isinstance(d, list): return [_coerce_dates(v) for v in d]
    if isinstance(d, (_dt.date, _dt.datetime)): return d.isoformat()
    return d


def _read_frontmatter(path: Path) -> dict:
    """Read YAML frontmatter (between two `---` lines) of a markdown file."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    return _coerce_dates(yaml.safe_load(m.group(1)) or {})


class TestNotesSchema(unittest.TestCase):
    def setUp(self):
        self.schema_path = BRAIN_SCHEMA_DOMAIN / "schemas" / "note.schema.json"

    def test_schema_exists(self):
        self.assertTrue(self.schema_path.exists(), f"missing: {self.schema_path}")

    def test_schema_validates_existing_notes(self):
        if not _HAS_JSONSCHEMA:
            self.skipTest("jsonschema not installed")
        if not BRAIN.exists():
            self.skipTest("brain not present on this machine")
        schema = json.loads(self.schema_path.read_text())
        note_files = list((BRAIN / "Notes").glob("pref-*.md"))
        self.assertGreater(len(note_files), 0, "no pref-*.md notes found")
        for nf in note_files:
            fm = _read_frontmatter(nf)
            try:
                validate(fm, schema)
            except Exception as e:
                self.fail(f"{nf.name} failed validation: {e}")


class TestBrainValidator(unittest.TestCase):
    def setUp(self):
        self.tool = BRAIN_TOOLS / "brain_validator.py"

    def test_validator_exists(self):
        self.assertTrue(self.tool.exists(), f"missing: {self.tool}")

    def test_validator_runs(self):
        if not self.tool.exists():
            self.skipTest("validator not yet written")
        import subprocess
        r = subprocess.run(
            ["python3", str(self.tool), "validate"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r.returncode, 0, f"validator exit {r.returncode}: {r.stderr}")
        self.assertIn("OK", r.stdout, "validator output should contain OK")


class TestBrainCodegen(unittest.TestCase):
    def setUp(self):
        self.tool = BRAIN_TOOLS / "brain_codegen.py"

    def test_codegen_exists(self):
        self.assertTrue(self.tool.exists())

    def test_codegen_persona_regen(self):
        if not self.tool.exists() or not BRAIN.exists():
            self.skipTest("dependencies missing")
        import subprocess
        # Codegen dry-run — should not error
        r = subprocess.run(
            ["python3", str(self.tool), "preview"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0, f"codegen preview failed: {r.stderr}")
        # Output should contain the rebuilt Top Beliefs block
        self.assertIn("Top Beliefs", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
