"""Tests for kaizen-brain block-level addressing — zero-roundtrip memory edits.

Per user 2026-05-19 — "index token efficient approach no roundtrips."
Heading-path addressing means one CLI call retrieves exactly the
needed block (Persona.md ## Top Beliefs / 3) without loading the
whole file. One more call edits it in place.

Design contract:
  PROGRAMMABLE  — parse_blocks / extract_block / replace_block pure
  REPRODUCIBLE  — same (text, path) → same address resolution
  CONSISTENT    — --json output for every subcommand
  DETERMINISTIC — no clock / random / env reads in pure layer
  REUSABLE      — works for any Markdown file with headings
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_BRAIN = _KZ / "scripts/brain/brain.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/brain"))
import _brain_blocks as _bb  # noqa: E402

_SAMPLE = """---
title: Sample
---

# Document

Intro paragraph.

## Mission

- Name: User
- Timezone: UTC

## Directives

- First directive
- Second directive
- Third directive

## Top Beliefs

1. [[Notes/pref-a]] — conf=0.95
2. [[Notes/pref-b]] — conf=0.90
3. [[Notes/pref-c]] — conf=0.85

## Evidence Log

- [2026-05-18] Quote: "x" → reason.
"""

# ─── parse_blocks ──────────────────────────────────────────────────────

class TestParseBlocks(unittest.TestCase):
    def test_returns_path_per_heading(self):
        blocks = _bb.parse_blocks(_SAMPLE)
        paths = [b["path"] for b in blocks]
        self.assertIn("Document", paths)
        self.assertIn("Document/Mission", paths)
        self.assertIn("Document/Directives", paths)
        self.assertIn("Document/Top Beliefs", paths)
        self.assertIn("Document/Evidence Log", paths)

    def test_block_line_ranges_bound_correctly(self):
        blocks = _bb.parse_blocks(_SAMPLE)
        by_path = {b["path"]: b for b in blocks}
        mission = by_path["Document/Mission"]
        # Mission block starts at its heading line + ends before Directives
        self.assertGreater(mission["end"], mission["start"])
        # Slicing actual lines should include the 2 list items
        sliced = "\n".join(_SAMPLE.splitlines()[mission["start"]:mission["end"]])
        self.assertIn("Name: User", sliced)
        self.assertIn("Timezone: UTC", sliced)
        self.assertNotIn("Directives", sliced)

    def test_level_field_carries_depth(self):
        blocks = _bb.parse_blocks(_SAMPLE)
        by_path = {b["path"]: b for b in blocks}
        self.assertEqual(by_path["Document"]["level"], 1)
        self.assertEqual(by_path["Document/Mission"]["level"], 2)

    def test_no_headings_returns_single_root(self):
        text = "Just some text with no headings.\n"
        blocks = _bb.parse_blocks(text)
        # Should return a synthetic root block covering the whole file
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["path"], "")
        self.assertEqual(blocks[0]["start"], 0)

# ─── extract_block ─────────────────────────────────────────────────────

class TestExtractBlock(unittest.TestCase):
    def test_extract_by_full_path(self):
        body = _bb.extract_block(_SAMPLE, "Document/Top Beliefs")
        self.assertIn("[[Notes/pref-a]]", body)
        self.assertIn("[[Notes/pref-b]]", body)
        self.assertIn("[[Notes/pref-c]]", body)
        # Sibling not included
        self.assertNotIn("Evidence Log", body)

    def test_extract_by_trailing_segment(self):
        # User-friendly: "Top Beliefs" (without "Document/" prefix) matches
        body = _bb.extract_block(_SAMPLE, "Top Beliefs")
        self.assertIn("[[Notes/pref-a]]", body)

    def test_extract_missing_returns_none(self):
        self.assertIsNone(_bb.extract_block(_SAMPLE, "NotThere"))

# ─── replace_block ─────────────────────────────────────────────────────

class TestReplaceBlock(unittest.TestCase):
    def test_replace_preserves_siblings(self):
        new_body = "## Top Beliefs\n\n1. [[Notes/new-belief]]\n"
        out = _bb.replace_block(_SAMPLE, "Top Beliefs", new_body)
        # New content in
        self.assertIn("new-belief", out)
        # Old content out
        self.assertNotIn("pref-a", out)
        # Siblings preserved
        self.assertIn("Mission", out)
        self.assertIn("Evidence Log", out)
        self.assertIn("Directives", out)

    def test_replace_missing_raises(self):
        with self.assertRaises(KeyError):
            _bb.replace_block(_SAMPLE, "NotThere", "x")

# ─── append_to_list_block ──────────────────────────────────────────────

class TestAppendToListBlock(unittest.TestCase):
    def test_append_numbered_list_item(self):
        out = _bb.append_to_list_block(_SAMPLE, "Top Beliefs",
                                         "4. [[Notes/pref-d]] — conf=0.80")
        self.assertIn("pref-d", out)
        # Still has the original 3 items
        self.assertIn("pref-a", out)
        self.assertIn("pref-b", out)
        self.assertIn("pref-c", out)
        # Append-only ordering — pref-d appears AFTER pref-c
        self.assertLess(out.index("pref-c"), out.index("pref-d"))

    def test_append_dash_list_item(self):
        out = _bb.append_to_list_block(_SAMPLE, "Directives",
                                         "- Fourth directive")
        self.assertIn("Fourth directive", out)
        self.assertLess(out.index("Third directive"),
                         out.index("Fourth directive"))

# ─── CLI integration ───────────────────────────────────────────────────

class TestBrainBlocksCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.file = self.tmp / "Note.md"
        self.file.write_text(_SAMPLE, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_BRAIN), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_blocks_subcommand_lists_paths(self):
        r = self._run("blocks", "--file", str(self.file), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        paths = [b["path"] for b in data["blocks"]]
        self.assertIn("Document/Top Beliefs", paths)

    def test_show_subcommand_extracts_block(self):
        r = self._run("show", "--file", str(self.file),
                       "--block", "Top Beliefs")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pref-a", r.stdout)
        # Sibling NOT in output
        self.assertNotIn("Evidence Log", r.stdout)

    def test_edit_replace_writes_atomically(self):
        r = self._run("edit", "--file", str(self.file),
                       "--block", "Top Beliefs",
                       "--replace", "## Top Beliefs\n\n1. [[Notes/replaced]]\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("replaced", text)
        self.assertNotIn("pref-a", text)
        # Siblings preserved
        self.assertIn("Mission", text)
        self.assertIn("Evidence Log", text)

    def test_edit_append_to_list_block(self):
        r = self._run("edit", "--file", str(self.file),
                       "--block", "Directives",
                       "--append", "- Fourth directive")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("Fourth directive", text)
        self.assertLess(text.index("Third directive"),
                         text.index("Fourth directive"))

    def test_show_missing_block_fails_gracefully(self):
        r = self._run("show", "--file", str(self.file), "--block", "Nope")
        self.assertNotEqual(r.returncode, 0)

class TestShortNameResolution(unittest.TestCase):
    """`--file Persona.md` → ~/.claude/.kaizen/brain/Persona.md.
    `--file MEMORY.md` → ~/.claude/projects/<slug>/memory/MEMORY.md.
    `--file Notes/X.md` → ~/.claude/.kaizen/brain/Notes/X.md.
    Literal paths (absolute or relative-to-cwd) still work unchanged.

    Sandbox via ``KAIZEN_BRAIN_DIR`` env override.
    """

    def setUp(self):
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Fake brain root + auto-memory dir
        self.fake_brain = self.tmp / "brain"
        self.fake_brain.mkdir()
        (self.fake_brain / "Persona.md").write_text(
            _SAMPLE, encoding="utf-8")
        (self.fake_brain / "Notes").mkdir()
        (self.fake_brain / "Notes" / "pref-x.md").write_text(
            _SAMPLE, encoding="utf-8")
        # Auto-memory dir (use env override KAIZEN_BETTER_MEMORY_DIR)
        self.fake_memory = self.tmp / "memory"
        self.fake_memory.mkdir()
        (self.fake_memory / "MEMORY.md").write_text(
            _SAMPLE, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self):
        e = os.environ.copy()
        e["KAIZEN_BRAIN_DIR"] = str(self.fake_brain)
        e["KAIZEN_BETTER_MEMORY_DIR"] = str(self.fake_memory)
        return e

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_BRAIN), *args],
            capture_output=True, text=True, timeout=15, env=self._env(),
        )

    def test_persona_md_short_name_resolves(self):
        r = self._run("blocks", "--file", "Persona.md", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["file"],
                         str(self.fake_brain / "Persona.md"))

    def test_memory_md_short_name_resolves(self):
        r = self._run("blocks", "--file", "MEMORY.md", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["file"],
                         str(self.fake_memory / "MEMORY.md"))

    def test_notes_subpath_short_name_resolves(self):
        r = self._run("blocks", "--file", "Notes/pref-x.md", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["file"],
                         str(self.fake_brain / "Notes" / "pref-x.md"))

    def test_literal_path_still_wins(self):
        """When --file is an absolute path that exists, no resolution."""
        literal = self.tmp / "Literal.md"
        literal.write_text(_SAMPLE)
        r = self._run("blocks", "--file", str(literal), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["file"], str(literal))

    def test_unknown_short_name_clear_error(self):
        r = self._run("blocks", "--file", "DoesNotExist.md")
        self.assertNotEqual(r.returncode, 0)
        # Error names the resolution attempts so the user can diagnose
        self.assertIn("brain", r.stderr.lower() + r.stdout.lower())

if __name__ == "__main__":
    unittest.main()
