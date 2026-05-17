"""Tests for the brain-specific iron-laws (v1.40+).

Four new auto-laws that protect the shipped `assets/starters/<name>/`
brain content from quality regressions. All scoped to in-repo starter
content (live brains under $KAIZEN_BRAIN_DIR are out of scope —
the gate sees only repo files).

  brain-note-schema       — frontmatter + type enum + belief confidence
  brain-rule-schema       — kaizen: block notes validate against schema
  starter-no-personal-data — no cherry86/@gmail/@anthropic/personal paths
  brain-no-orphan-toplevel — starter root only has PARA dirs + sanctioned
                              top-level files
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _iron_laws as il  # noqa: E402


def _ctx(repo_root: Path, scope: str = "all") -> "il.CheckContext":
    return il.CheckContext(
        repo_root=repo_root,
        plugin_root=repo_root / "plugins" / "kaizen",
        scope=scope,
        changed=[],
        added=[],
    )


def _make_starter(repo_root: Path, name: str = "test") -> Path:
    starter = repo_root / "plugins" / "kaizen" / "assets" / "starters" / name
    notes = starter / "Notes"
    notes.mkdir(parents=True)
    (starter / "Persona.md").write_text(
        "---\ncreated: 2026-05-17\ntags: [persona]\n---\n\n# Persona\n"
    )
    (starter / "REMEMBER.md").write_text("# REMEMBER\n")
    (starter / "SessionNotes.md").write_text("# Session Notes\n")
    for sub in ("Inbox", "Journal", "Projects", "People", "Areas",
                 "Resources", "Tasks", "Templates", "Archive"):
        (starter / sub).mkdir()
    return starter


class BrainNoteSchema(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.starter = _make_starter(self.root)
        self.notes = self.starter / "Notes"

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_note_no_findings(self):
        (self.notes / "good.md").write_text(
            "---\nname: Good note\ntype: world-fact\n"
            "tags: []\nsources_count: 1\n---\n\n# body\n"
        )
        self.assertEqual(il.check_brain_note_schema(_ctx(self.root)), [])

    def test_missing_name_flagged(self):
        (self.notes / "noname.md").write_text(
            "---\ntype: world-fact\n---\n\n# body\n"
        )
        f = il.check_brain_note_schema(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("name", f[0].message.lower())

    def test_missing_type_flagged(self):
        (self.notes / "notype.md").write_text(
            "---\nname: Untyped\n---\n\n# body\n"
        )
        f = il.check_brain_note_schema(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("type", f[0].message.lower())

    def test_invalid_type_enum_flagged(self):
        (self.notes / "bad-type.md").write_text(
            "---\nname: Bad\ntype: gibberish\n---\n\n# body\n"
        )
        f = il.check_brain_note_schema(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("gibberish", f[0].message)

    def test_belief_without_confidence_flagged(self):
        (self.notes / "bare-belief.md").write_text(
            "---\nname: Bare belief\ntype: belief\n---\n\n# body\n"
        )
        f = il.check_brain_note_schema(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("confidence", f[0].message.lower())

    def test_belief_with_confidence_ok(self):
        (self.notes / "good-belief.md").write_text(
            "---\nname: Good\ntype: belief\nconfidence: 0.85\n---\n\nbody\n"
        )
        self.assertEqual(il.check_brain_note_schema(_ctx(self.root)), [])

    def test_world_fact_without_confidence_ok(self):
        (self.notes / "wf.md").write_text(
            "---\nname: A fact\ntype: world-fact\n---\n\nbody\n"
        )
        self.assertEqual(il.check_brain_note_schema(_ctx(self.root)), [])


class BrainRuleSchema(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.starter = _make_starter(self.root)
        self.notes = self.starter / "Notes"

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_deletion_allow_rule_no_findings(self):
        (self.notes / "kaizen-allow-logs.md").write_text(
            "---\nname: Allow log deletions\n"
            "description: x\ntype: behaviour\n"
            "kaizen:\n  rule_type: deletion-allow\n"
            "  path_glob: \"**/*.log\"\n---\n\nbody\n"
        )
        self.assertEqual(il.check_brain_rule_schema(_ctx(self.root)), [])

    def test_invalid_rule_type_flagged(self):
        (self.notes / "kaizen-bad.md").write_text(
            "---\nname: Bad rule\ndescription: x\ntype: behaviour\n"
            "kaizen:\n  rule_type: not-a-real-type\n"
            "  path_glob: \"*\"\n---\n\nbody\n"
        )
        f = il.check_brain_rule_schema(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("rule_type", f[0].message.lower())

    def test_deletion_allow_missing_path_glob_flagged(self):
        (self.notes / "kaizen-no-glob.md").write_text(
            "---\nname: x\ndescription: x\ntype: behaviour\n"
            "kaizen:\n  rule_type: deletion-allow\n---\n\nbody\n"
        )
        f = il.check_brain_rule_schema(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("path_glob", f[0].message.lower())

    def test_note_without_kaizen_block_ignored(self):
        (self.notes / "regular.md").write_text(
            "---\nname: Regular\ntype: belief\nconfidence: 0.8\n"
            "---\n\nbody\n"
        )
        self.assertEqual(il.check_brain_rule_schema(_ctx(self.root)), [])


class StarterNoPersonalData(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.starter = _make_starter(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_starter_no_findings(self):
        self.assertEqual(il.check_starter_no_personal_data(_ctx(self.root)), [])

    def test_username_in_note_flagged(self):
        (self.starter / "Notes" / "leaky.md").write_text(
            "---\nname: x\ntype: belief\nconfidence: 0.8\n---\n"
            "Example path: /home/cherry86/workspace/foo\n"
        )
        f = il.check_starter_no_personal_data(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("cherry86", f[0].message)

    def test_email_address_flagged(self):
        (self.starter / "Persona.md").write_text(
            "---\ntags: [persona]\n---\n# Persona\n\nContact me@gmail.com\n"
        )
        f = il.check_starter_no_personal_data(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("email", f[0].message.lower())

    def test_anthropic_email_flagged(self):
        (self.starter / "Notes" / "leak.md").write_text(
            "---\nname: x\ntype: world-fact\n---\nsource: user@anthropic.com\n"
        )
        f = il.check_starter_no_personal_data(_ctx(self.root))
        self.assertTrue(f)

    def test_specific_workspace_name_flagged(self):
        (self.starter / "Notes" / "leak.md").write_text(
            "---\nname: x\ntype: world-fact\n---\nFrom shodan workspace\n"
        )
        f = il.check_starter_no_personal_data(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("shodan", f[0].message.lower())

    def test_placeholder_paths_ok(self):
        (self.starter / "Notes" / "ok.md").write_text(
            "---\nname: x\ntype: world-fact\n---\n"
            "Example: <your project> at ~/<user>/workspace/<project>/\n"
        )
        self.assertEqual(il.check_starter_no_personal_data(_ctx(self.root)), [])


class BrainNoOrphanTopLevel(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.starter = _make_starter(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_canonical_starter_no_findings(self):
        self.assertEqual(il.check_brain_no_orphan_toplevel(_ctx(self.root)), [])

    def test_orphan_file_at_root_flagged(self):
        (self.starter / "scratch.md").write_text("ad-hoc note\n")
        f = il.check_brain_no_orphan_toplevel(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("scratch.md", f[0].message)

    def test_README_md_is_allowed(self):
        (self.starter / "README.md").write_text("# starter README\n")
        self.assertEqual(il.check_brain_no_orphan_toplevel(_ctx(self.root)), [])

    def test_orphan_dir_flagged(self):
        (self.starter / "UnknownDir").mkdir()
        f = il.check_brain_no_orphan_toplevel(_ctx(self.root))
        self.assertTrue(f)
        self.assertIn("UnknownDir", f[0].message)


if __name__ == "__main__":
    unittest.main()
