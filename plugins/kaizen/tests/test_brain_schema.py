"""Tests for brain_schema.py — path-inferred validate-and-upgrade.

Port of upstream remember-md/remember/tests/schema-validate-upgrade.test.js.
Covers infer_expected_schema across the 7 path shapes + apply_missing_frontmatter_fields
+ append_missing_persona_sections + validate_and_upgrade end-to-end.

Sandboxed via tempfile — no production brain touched.
"""
from __future__ import annotations

import datetime as _dt
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KZ / "scripts/brain"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import brain_schema as bs  # noqa: E402

class TestInferExpectedSchema(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        for sub in ("Notes", "People", "Areas", "Journal",
                    "Projects/foo", "Projects/foo/decisions",
                    "Projects/foo/meetings"):
            (self.brain / sub).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_outside_brain_root_is_passthrough(self):
        outside = Path("/tmp/somewhere/else.md")
        out = bs.infer_expected_schema(outside, self.brain)
        self.assertEqual(out["kind"], "passthrough")

    def test_no_brain_root_is_passthrough(self):
        out = bs.infer_expected_schema(self.brain / "Notes" / "x.md", None)
        self.assertEqual(out["kind"], "passthrough")

    def test_persona_md(self):
        p = self.brain / "Persona.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "persona-sections")
        self.assertEqual(out["required_sections"], tuple(bs.PERSONA_SECTIONS))

    def test_notes(self):
        p = self.brain / "Notes" / "pref-x.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "world-fact")
        self.assertIn("type", out["required_fields"])
        self.assertIn("freshness", out["required_fields"])
        self.assertIn("sources_count", out["required_fields"])

    def test_people(self):
        p = self.brain / "People" / "alice.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "observation")
        self.assertEqual(out["defaults"]["last_consolidated"], "{TODAY}")

    def test_areas(self):
        p = self.brain / "Areas" / "fitness.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "observation")

    def test_journal_dated(self):
        p = self.brain / "Journal" / "2026-05-20.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "experience")

    def test_journal_undated_is_passthrough(self):
        p = self.brain / "Journal" / "notes-random.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "passthrough")

    def test_projects_main_file(self):
        p = self.brain / "Projects" / "foo" / "foo.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "observation")

    def test_projects_decisions(self):
        p = self.brain / "Projects" / "foo" / "decisions" / "auth.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "world-fact")

    def test_projects_meetings(self):
        p = self.brain / "Projects" / "foo" / "meetings" / "kickoff.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "l2-typed")
        self.assertEqual(out["default_type"], "world-fact")

    def test_projects_other_subdir_is_passthrough(self):
        (self.brain / "Projects" / "foo" / "randomdir").mkdir()
        p = self.brain / "Projects" / "foo" / "randomdir" / "x.md"
        p.touch()
        out = bs.infer_expected_schema(p, self.brain)
        self.assertEqual(out["kind"], "passthrough")

class TestApplyMissingFrontmatterFields(unittest.TestCase):
    def test_adds_missing_fields_to_existing_fm(self):
        text = "---\nname: foo\n---\n# body"
        defaults = {"type": "world-fact", "sources_count": 1}
        out = bs.apply_missing_frontmatter_fields(text, defaults, "2026-05-20")
        self.assertIn("type: world-fact", out["text"])
        self.assertIn("sources_count: 1", out["text"])
        # Existing field preserved
        self.assertIn("name: foo", out["text"])
        self.assertEqual(set(out["added_fields"]), {"type", "sources_count"})

    def test_skips_fields_already_present(self):
        text = "---\nname: foo\ntype: belief\n---\n# body"
        defaults = {"type": "world-fact"}
        out = bs.apply_missing_frontmatter_fields(text, defaults, "2026-05-20")
        # `type` is already present (as belief) — must NOT be overwritten
        self.assertIn("type: belief", out["text"])
        self.assertNotIn("type: world-fact", out["text"])
        self.assertEqual(out["added_fields"], [])

    def test_substitutes_today_placeholder(self):
        text = "---\nname: foo\n---\n# body"
        defaults = {"last_consolidated": "{TODAY}"}
        out = bs.apply_missing_frontmatter_fields(text, defaults, "2026-05-20")
        self.assertIn("last_consolidated: 2026-05-20", out["text"])

    def test_creates_frontmatter_when_missing(self):
        text = "# just a body"
        defaults = {"type": "world-fact", "sources_count": 1}
        out = bs.apply_missing_frontmatter_fields(text, defaults, "2026-05-20")
        self.assertTrue(out["text"].startswith("---\n"))
        self.assertIn("type: world-fact", out["text"])
        self.assertIn("# just a body", out["text"])

class TestAppendMissingPersonaSections(unittest.TestCase):
    def test_appends_missing_sections(self):
        text = "# Persona\n\n## Mission\n\n_role_\n"
        out = bs.append_missing_persona_sections(text, bs.PERSONA_SECTIONS)
        self.assertIn("## Directives", out["text"])
        self.assertIn("## Top Beliefs", out["text"])
        self.assertIn("## Evidence Log", out["text"])
        # Mission preserved
        self.assertIn("_role_", out["text"])
        self.assertEqual(set(out["added_sections"]),
                         {"Directives", "Top Beliefs", "Evidence Log"})

    def test_no_change_when_all_present(self):
        text = "\n".join([
            "# Persona", "",
            "## Mission", "_x_", "",
            "## Directives", "_y_", "",
            "## Top Beliefs", "_z_", "",
            "## Evidence Log", "_w_", "",
        ])
        out = bs.append_missing_persona_sections(text, bs.PERSONA_SECTIONS)
        self.assertEqual(out["added_sections"], [])
        self.assertEqual(out["text"], text)

class TestValidateAndUpgrade(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        for sub in ("Notes", "People", "Projects/foo/decisions"):
            (self.brain / sub).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_passthrough_for_file_outside_brain(self):
        outside = Path(self._tmp.name).parent / "outside.md"
        outside.write_text("# nothing\n")
        try:
            out = bs.validate_and_upgrade(outside, brain_root=self.brain)
            self.assertFalse(out["changed"])
        finally:
            outside.unlink(missing_ok=True)

    def test_missing_file_returns_blank_result(self):
        p = self.brain / "Notes" / "ghost.md"  # does not exist
        out = bs.validate_and_upgrade(p, brain_root=self.brain)
        self.assertFalse(out["changed"])

    def test_notes_file_gets_missing_fields(self):
        p = self.brain / "Notes" / "pref-x.md"
        p.write_text("---\nname: pref-x\n---\n# body\n")
        out = bs.validate_and_upgrade(p, brain_root=self.brain, today="2026-05-20")
        self.assertTrue(out["changed"])
        text = p.read_text()
        self.assertIn("type: world-fact", text)
        self.assertIn("freshness: stable", text)
        self.assertIn("sources_count: 1", text)

    def test_belief_without_confidence_gets_default_and_warning(self):
        p = self.brain / "Notes" / "pref-b.md"
        p.write_text("---\nname: pref-b\ntype: belief\n---\n# body\n")
        out = bs.validate_and_upgrade(p, brain_root=self.brain, today="2026-05-20")
        self.assertTrue(out["changed"])
        text = p.read_text()
        # confidence defaulted to 0.5 — and a warning emitted
        self.assertIn("confidence: 0.5", text)
        self.assertTrue(any("0.5" in w for w in out["warnings"]),
                        f"warnings should mention default: {out['warnings']}")

    def test_persona_missing_sections_get_appended(self):
        p = self.brain / "Persona.md"
        p.write_text("# Persona\n\n## Mission\n\nbody\n")
        out = bs.validate_and_upgrade(p, brain_root=self.brain)
        self.assertTrue(out["changed"])
        text = p.read_text()
        self.assertIn("## Directives", text)
        self.assertIn("## Top Beliefs", text)
        self.assertIn("## Evidence Log", text)

    def test_persona_already_complete_is_no_op(self):
        p = self.brain / "Persona.md"
        complete = "\n".join([
            "# Persona", "",
            "## Mission", "_x_", "",
            "## Directives", "_y_", "",
            "## Top Beliefs", "_z_", "",
            "## Evidence Log", "_w_", "",
        ])
        p.write_text(complete)
        before = p.read_text()
        out = bs.validate_and_upgrade(p, brain_root=self.brain)
        self.assertFalse(out["changed"])
        self.assertEqual(p.read_text(), before)

    def test_idempotent_repeat_invocation(self):
        p = self.brain / "Notes" / "pref-y.md"
        p.write_text("---\nname: pref-y\n---\n# body\n")
        bs.validate_and_upgrade(p, brain_root=self.brain, today="2026-05-20")
        first = p.read_text()
        out2 = bs.validate_and_upgrade(p, brain_root=self.brain, today="2026-05-20")
        # Second call must not change anything
        self.assertFalse(out2["changed"])
        self.assertEqual(p.read_text(), first)

    def test_decisions_subdir_gets_world_fact(self):
        p = self.brain / "Projects" / "foo" / "decisions" / "auth.md"
        p.write_text("---\nname: auth\n---\n# body\n")
        out = bs.validate_and_upgrade(p, brain_root=self.brain)
        self.assertTrue(out["changed"])
        text = p.read_text()
        self.assertIn("type: world-fact", text)
        self.assertIn("freshness: stable", text)

class TestDryRun(unittest.TestCase):
    """dry_run=True surfaces what would change without writing.

    Closes the last unique-value bullet from self_improving/brain_validator
    (which was read-only by design — never wrote)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / "Notes").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_reports_would_change_without_write(self):
        p = self.brain / "Notes" / "pref-x.md"
        original = "---\nname: pref-x\n---\n# body\n"
        p.write_text(original, encoding="utf-8")
        out = bs.validate_and_upgrade(
            p, brain_root=self.brain, today="2026-05-20", dry_run=True
        )
        self.assertTrue(out["changed"], "should report would-change")
        # File unmodified
        self.assertEqual(p.read_text(), original)

    def test_dry_run_on_clean_file_reports_no_change(self):
        p = self.brain / "Notes" / "pref-y.md"
        p.write_text(
            "---\nname: pref-y\ntype: world-fact\nfreshness: stable\nsources_count: 1\n---\n# y\n",
            encoding="utf-8",
        )
        out = bs.validate_and_upgrade(p, brain_root=self.brain, dry_run=True)
        self.assertFalse(out["changed"])

class TestCheckLinks(unittest.TestCase):
    """check_links(): audit [[ref]] cross-references in Persona + Notes.

    Extracted from self_improving/brain_validator::cmd_links during the
    consolidation arc."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / "Notes").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_brain_returns_zero(self):
        out = bs.check_links(self.brain)
        self.assertEqual(out, {"refs_count": 0, "broken": []})

    def test_resolves_notes_ref(self):
        (self.brain / "Notes" / "pref-x.md").write_text(
            "---\ntype: belief\n---\n# x\n", encoding="utf-8")
        (self.brain / "Persona.md").write_text(
            "# Persona\n\n## Top Beliefs\n\n1. [[Notes/pref-x]]\n", encoding="utf-8")
        out = bs.check_links(self.brain)
        self.assertEqual(out["refs_count"], 1)
        self.assertEqual(out["broken"], [])

    def test_flags_broken_ref(self):
        (self.brain / "Persona.md").write_text(
            "## Top Beliefs\n\n1. [[Notes/ghost]]\n", encoding="utf-8")
        out = bs.check_links(self.brain)
        self.assertEqual(out["refs_count"], 1)
        self.assertEqual(len(out["broken"]), 1)
        self.assertEqual(out["broken"][0][1], "Notes/ghost")

if __name__ == "__main__":
    unittest.main()
