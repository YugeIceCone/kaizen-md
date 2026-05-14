"""Tests for the iron-laws skill — loader, codegen, checker, CLI, MCP.

The iron-laws skill's backing code is split across two dirs:
  - skills/iron-laws/application/  — _loader.py, codegen.py
  - skills/workflow/scripts/       — _iron_laws.py, iron_laws.py, iron_laws_mcp.py
Both are put on sys.path here.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_APP = _PLUGIN_ROOT / "skills" / "iron-laws" / "application"
_SCRIPTS = _PLUGIN_ROOT / "skills" / "workflow" / "scripts"
_DOMAIN = _PLUGIN_ROOT / "skills" / "iron-laws" / "domain"
for _p in (_APP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class TestLoader(unittest.TestCase):
    def test_load_laws_returns_all(self):
        import _loader
        laws = _loader.load_laws()
        self.assertEqual(len(laws), 21)

    def test_every_law_has_required_fields(self):
        import _loader
        for law in _loader.load_laws():
            for field in ("id", "statement", "severity", "enforcement", "why"):
                self.assertIn(field, law, f"{law.get('id')} missing {field}")

    def test_auto_laws_have_check_manual_do_not(self):
        import _loader
        for law in _loader.load_laws():
            if law["enforcement"] == "auto":
                self.assertTrue(law.get("check"), f"{law['id']} auto but no check")
            else:
                self.assertNotIn("check", law, f"{law['id']} manual but has check")

    def test_load_laws_by_id(self):
        import _loader
        by_id = _loader.load_laws_by_id()
        self.assertIn("no-modify-vendored", by_id)
        self.assertEqual(by_id["no-modify-vendored"]["severity"], "hard")

    def test_auto_and_manual_filters(self):
        import _loader
        auto = _loader.auto_laws()
        manual = _loader.manual_laws()
        self.assertEqual(len(auto), 15)
        self.assertEqual(len(manual), 6)
        self.assertTrue(all(l["enforcement"] == "auto" for l in auto))

    def test_load_laws_rejects_schema_invalid(self):
        import _loader
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False
        ) as fh:
            fh.write("version: 1\nlaws:\n  - id: bad\n")  # missing required fields
            bad = fh.name
        try:
            with self.assertRaises(Exception):
                _loader.load_laws(path=Path(bad))
        finally:
            Path(bad).unlink()


class TestCodegen(unittest.TestCase):
    def test_render_is_deterministic(self):
        import codegen
        self.assertEqual(codegen._render(), codegen._render())

    def test_check_passes_when_reference_in_sync(self):
        import codegen
        # references/iron-laws.md is committed in-sync; --check must pass.
        self.assertEqual(codegen.generate(check_only=True), 0)

    def test_check_detects_drift(self):
        import codegen
        original = codegen.REF_PATH
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".md", delete=False
            ) as fh:
                fh.write("stale content — not what _render() produces\n")
                stale = fh.name
            codegen.REF_PATH = Path(stale)
            self.assertEqual(codegen.generate(check_only=True), 1)
        finally:
            codegen.REF_PATH = original
            Path(stale).unlink()

    def test_generated_reference_has_do_not_edit_header(self):
        ref = (_DOMAIN.parent / "references" / "iron-laws.md").read_text()
        self.assertIn("DO NOT HAND-EDIT", ref)
        self.assertIn("21 laws", ref)


if __name__ == "__main__":
    unittest.main()
