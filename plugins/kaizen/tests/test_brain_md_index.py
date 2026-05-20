"""Tests for brain_md_index.py — markdown brain inventory.

Port-test for upstream build-index.js. Covers scan_* per-category,
format_full (tables), format_compact (one-line summaries).

Sandboxed via tempfile.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KZ / "scripts/brain"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import brain_md_index as bm  # noqa: E402

class _BrainSandbox(unittest.TestCase):
    """Per-test sandboxed brain with the PARA dir skeleton."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        for sub in ("People", "Projects", "Areas", "Notes", "Tasks", "Journal"):
            (self.brain / sub).mkdir()

    def tearDown(self):
        self._tmp.cleanup()

class TestScanPeople(_BrainSandbox):
    def test_empty(self):
        self.assertEqual(bm.scan_people(self.brain), [])

    def test_extracts_role_and_org(self):
        (self.brain / "People" / "alice.md").write_text(
            "---\nname: Alice\nrole: Engineer\norg: ACME\nlast_contact: 2026-05-19\ntags: dev\n---\n# Alice\n",
            encoding="utf-8",
        )
        out = bm.scan_people(self.brain)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], "alice")
        self.assertEqual(out[0]["role"], "Engineer")
        self.assertEqual(out[0]["org"], "ACME")
        self.assertEqual(out[0]["last_contact"], "2026-05-19")

    def test_organization_alias_for_org(self):
        (self.brain / "People" / "bob.md").write_text(
            "---\nname: Bob\norganization: Beta Co\n---\n# Bob\n",
            encoding="utf-8",
        )
        out = bm.scan_people(self.brain)
        self.assertEqual(out[0]["org"], "Beta Co")

    def test_falls_back_to_titlecased_stem(self):
        (self.brain / "People" / "charlie-davis.md").write_text(
            "---\nrole: Director\n---\n",
            encoding="utf-8",
        )
        out = bm.scan_people(self.brain)
        # No `name:` and no H1 → derive from stem
        self.assertEqual(out[0]["name"], "Charlie Davis")

class TestScanProjects(_BrainSandbox):
    def test_uses_main_named_file(self):
        proj = self.brain / "Projects" / "foo"
        proj.mkdir()
        (proj / "foo.md").write_text(
            "---\nstatus: active\nupdated: 2026-05-20\n---\n# Foo Project\n",
            encoding="utf-8",
        )
        (proj / "design.md").write_text("---\n---\n", encoding="utf-8")
        out = bm.scan_projects(self.brain)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], "foo")
        self.assertEqual(out[0]["name"], "Foo Project")
        self.assertEqual(out[0]["status"], "active")
        self.assertEqual(out[0]["sub_notes"], 1)

    def test_falls_back_to_first_md_when_no_named_file(self):
        proj = self.brain / "Projects" / "bar"
        proj.mkdir()
        (proj / "design.md").write_text(
            "---\nstatus: paused\n---\n# Bar Design\n",
            encoding="utf-8",
        )
        out = bm.scan_projects(self.brain)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], "bar")

    def test_skips_directory_without_any_md(self):
        (self.brain / "Projects" / "empty").mkdir()
        out = bm.scan_projects(self.brain)
        self.assertEqual(out, [])

class TestScanAreas(_BrainSandbox):
    def test_extracts_updated(self):
        (self.brain / "Areas" / "fitness.md").write_text(
            "---\nupdated: 2026-05-15\n---\n# Fitness\n",
            encoding="utf-8",
        )
        out = bm.scan_areas(self.brain)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["file"], "fitness")
        self.assertEqual(out[0]["updated"], "2026-05-15")

class TestScanNotes(_BrainSandbox):
    def test_sorted_alphabetically(self):
        for slug in ("z-last", "a-first", "m-mid"):
            (self.brain / "Notes" / f"{slug}.md").write_text(
                f"---\ntags: x\n---\n# {slug}\n",
                encoding="utf-8",
            )
        out = bm.scan_notes(self.brain)
        self.assertEqual([n["file"] for n in out], ["a-first", "m-mid", "z-last"])

class TestScanTasks(_BrainSandbox):
    def test_counts_per_section(self):
        (self.brain / "Tasks").mkdir(exist_ok=True)
        (self.brain / "Tasks" / "tasks.md").write_text("""\
# Tasks

## Focus
- [ ] one
- [x] two

## Next Up
- [ ] three

## Backlog
- [ ] four
- [ ] five
- [ ] six

## Done
- [x] seven
""", encoding="utf-8")
        out = bm.scan_tasks(self.brain)
        self.assertEqual(out, {"focus": 2, "next_up": 1, "backlog": 3, "done": 1})

    def test_returns_zeros_when_missing(self):
        out = bm.scan_tasks(self.brain)
        self.assertEqual(out, {"focus": 0, "next_up": 0, "backlog": 0, "done": 0})

class TestScanJournal(_BrainSandbox):
    def test_latest_is_last_alphabetical(self):
        for d in ("2026-05-15", "2026-05-20", "2026-05-18"):
            (self.brain / "Journal" / f"{d}.md").write_text("# day\n", encoding="utf-8")
        out = bm.scan_journal(self.brain)
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["latest"], "2026-05-20")

class TestFormatCompact(_BrainSandbox):
    def test_includes_all_categories(self):
        (self.brain / "People" / "alice.md").write_text("---\n---\n# Alice\n", encoding="utf-8")
        (self.brain / "Areas" / "fitness.md").write_text("---\n---\n# Fitness\n", encoding="utf-8")
        (self.brain / "Notes" / "pref-x.md").write_text("---\n---\n# pref-x\n", encoding="utf-8")
        out = bm.format_compact(self.brain)
        self.assertIn(f"BRAIN INDEX ({self.brain})", out)
        self.assertIn("People: alice", out)
        self.assertIn("Areas: fitness", out)
        self.assertIn("Notes (1): pref-x", out)
        self.assertIn("Projects: none", out)
        self.assertIn("Journal: 0 entries", out)

    def test_notes_truncated_at_20(self):
        for i in range(25):
            (self.brain / "Notes" / f"pref-{i:02d}.md").write_text(
                f"---\n---\n# pref-{i:02d}\n", encoding="utf-8",
            )
        out = bm.format_compact(self.brain)
        self.assertIn("Notes (25):", out)
        self.assertIn("...", out)
        # First 20 listed, the 21st (pref-20) not listed (when sorted alphabetically)
        self.assertIn("pref-19", out)

class TestFormatFull(_BrainSandbox):
    def test_uses_tables(self):
        (self.brain / "People" / "alice.md").write_text(
            "---\nname: Alice\nrole: PM\n---\n# Alice\n",
            encoding="utf-8",
        )
        out = bm.format_full(self.brain)
        self.assertIn("# Knowledge Index", out)
        self.assertIn("## People", out)
        self.assertIn("| Name | Role/Org", out)
        self.assertIn("[[People/alice\\|Alice]]", out)
        # Empty sections still rendered with "None yet"
        self.assertIn("## Projects\n*None yet*", out)

if __name__ == "__main__":
    unittest.main()
