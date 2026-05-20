"""Phase M: brain Notes with `paths:` frontmatter auto-emit as project rules.

A Note opts into path-scoped rule emission by declaring `paths:` in
its YAML frontmatter. The daemon walks ~/.claude/.kaizen/brain/Notes/,
finds opt-in Notes, and writes one rule per Note to
<project>/.claude/rules/note-<slug>.md with the Note's paths copied.

Opt-in design: only Notes that explicitly declare `paths:` get emitted.
Prevents flooding 38 rule files per project. Notes without `paths:`
stay brain-only (reachable via kaizen-brain show / semantic search).

Pure layer: scan_path_scoped_notes(brain_root) → list[{slug, paths,
text, note_path}]
Adapter: write_note_rules(brain_root, project_root) writes rules +
prunes obsolete daemon-authored ones.

Sandbox: KAIZEN_BRAIN_DIR points brain at a tempfile dir.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
def _seed_note(brain: Path, name: str, frontmatter: str, body: str = "body"):
    notes = brain / "Notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / f"{name}.md").write_text(
        f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")

class TestScanPathScopedNotes(unittest.TestCase):

    def test_returns_empty_when_no_notes(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            (brain / "Notes").mkdir()
            found = al.scan_path_scoped_notes(brain)
        self.assertEqual(found, [])

    def test_includes_note_with_paths_field(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            _seed_note(brain, "pref-api-style",
                       "type: preference\npaths: ['src/api/**/*.ts']")
            found = al.scan_path_scoped_notes(brain)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["slug"], "pref-api-style")
        self.assertEqual(found[0]["paths"], ["src/api/**/*.ts"])

    def test_excludes_note_without_paths_field(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            _seed_note(brain, "pref-no-deletions",
                       "type: preference")
            found = al.scan_path_scoped_notes(brain)
        self.assertEqual(found, [])

    def test_parses_yaml_list_form(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            # Multi-line YAML list (the doc's example syntax)
            _seed_note(brain, "pref-multi",
                       "type: preference\npaths:\n  - 'src/**/*.py'\n  - 'tests/**/*.py'")
            found = al.scan_path_scoped_notes(brain)
        self.assertEqual(len(found), 1)
        self.assertIn("src/**/*.py", found[0]["paths"])
        self.assertIn("tests/**/*.py", found[0]["paths"])

    def test_ignores_malformed_frontmatter(self):
        """Notes with broken YAML get skipped, not crash."""
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            notes = brain / "Notes"
            notes.mkdir()
            (notes / "broken.md").write_text("---\nname: 'unterminated\n---\nbody")
            _seed_note(brain, "ok-note",
                       "type: preference\npaths: ['x']")
            found = al.scan_path_scoped_notes(brain)
        slugs = [n["slug"] for n in found]
        self.assertIn("ok-note", slugs)
        self.assertNotIn("broken", slugs)

class TestWriteNoteRules(unittest.TestCase):

    def test_writes_one_rule_per_path_scoped_note(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            project = Path(td) / "project"
            project.mkdir()
            _seed_note(brain, "pref-api",
                       "paths: ['src/api/**/*.ts']",
                       body="API style rule body")
            _seed_note(brain, "pref-tests",
                       "paths: ['tests/**']",
                       body="Test rule body")
            written = al.write_note_rules(brain, project)
            rules_dir = project / ".claude" / "rules"
            self.assertEqual(len(written), 2)
            self.assertTrue((rules_dir / "note-pref-api.md").is_file())
            self.assertTrue((rules_dir / "note-pref-tests.md").is_file())

    def test_rule_includes_note_paths_in_frontmatter(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            project = Path(td) / "project"
            project.mkdir()
            _seed_note(brain, "pref-api",
                       "paths: ['src/api/**/*.ts', 'lib/**/*.ts']",
                       body="rule body")
            al.write_note_rules(brain, project)
            content = (project / ".claude" / "rules" /
                       "note-pref-api.md").read_text()
        self.assertTrue(content.startswith("---\n"),
            "must start with YAML frontmatter (line 1)")
        self.assertIn("src/api/**/*.ts", content)
        self.assertIn("lib/**/*.ts", content)
        # The Note body is preserved in the rule
        self.assertIn("rule body", content)

    def test_rule_uses_note_prefix_to_namespace(self):
        """`note-<slug>.md` prefix prevents collision with directive
        gates (which use plain `<slug>.md`)."""
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            project = Path(td) / "project"
            project.mkdir()
            _seed_note(brain, "pref-x", "paths: ['**/*']")
            al.write_note_rules(brain, project)
            files = sorted(p.name for p in
                           (project / ".claude" / "rules").glob("*.md"))
        self.assertEqual(files, ["note-pref-x.md"])

    def test_prunes_obsolete_daemon_authored_rules(self):
        import auto_load as al
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            brain.mkdir()
            project = Path(td) / "project"
            project.mkdir()
            rules_dir = project / ".claude" / "rules"
            rules_dir.mkdir(parents=True)
            # Daemon-authored obsolete (matches note-* prefix + marker)
            (rules_dir / "note-pref-obsolete.md").write_text(
                "<!-- AUTO-GENERATED by kaizen daemon. -->\nbody\n")
            # Hand-authored note-prefixed (no marker) — preserved
            (rules_dir / "note-custom.md").write_text("---\npaths: ['**/*']\n---\nmine\n")
            _seed_note(brain, "pref-new", "paths: ['**/*']")
            al.write_note_rules(brain, project)
            remaining = sorted(p.name for p in rules_dir.glob("note-*.md"))
        self.assertNotIn("note-pref-obsolete.md", remaining)
        # Hand-authored preserved
        self.assertIn("note-custom.md", remaining)
        self.assertIn("note-pref-new.md", remaining)

if __name__ == "__main__":
    unittest.main()
