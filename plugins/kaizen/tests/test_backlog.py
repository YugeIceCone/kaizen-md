#!/usr/bin/env python3
"""Unit tests for backlog.py — pure-Python, no subprocess.

Run:
    python3 -m unittest tests.test_backlog -v
    OR
    python3 tests/test_backlog.py

Covers:
    - empty_store envelope shape
    - next_id increments correctly + handles gaps
    - render_md output is deterministic + has expected sections
    - load_store backwards-compat (missing fields default-filled)
    - save_store / load_store round-trip
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make backlog.py importable
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "kaizen" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import backlog as bl  # noqa: E402


class TestEnvelope(unittest.TestCase):
    def test_empty_store_shape(self):
        s = bl.empty_store()
        self.assertEqual(s["schema_version"], 1)
        self.assertEqual(s["kind"], "kaizen.backlog")
        self.assertEqual(s["items"], [])
        self.assertEqual(s["decisions"], [])
        self.assertIn("created", s["metadata"])
        self.assertIn("updated", s["metadata"])
        self.assertIsNone(s["metadata"]["active_workflow_ref"])

    def test_load_backwards_compat(self):
        """A minimal `{schema_version, items}` JSON gets defaults filled in."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"schema_version": 1, "items": []}, f)
            p = Path(f.name)
        try:
            s = bl.load_store(p)
            self.assertEqual(s["kind"], "kaizen.backlog")
            self.assertIn("metadata", s)
            self.assertEqual(s["decisions"], [])
        finally:
            p.unlink()


class TestNextId(unittest.TestCase):
    def test_empty_store_starts_at_001(self):
        s = bl.empty_store()
        self.assertEqual(bl.next_id(s), "BK-001")

    def test_increments_from_existing(self):
        s = bl.empty_store()
        s["items"] = [{"id": "BK-001"}, {"id": "BK-002"}]
        self.assertEqual(bl.next_id(s), "BK-003")

    def test_handles_gaps(self):
        s = bl.empty_store()
        s["items"] = [{"id": "BK-001"}, {"id": "BK-005"}, {"id": "BK-003"}]
        self.assertEqual(bl.next_id(s), "BK-006")

    def test_ignores_non_bk_ids(self):
        s = bl.empty_store()
        s["items"] = [{"id": "FOO-1"}, {"id": "BK-002"}, {"id": "weird"}]
        self.assertEqual(bl.next_id(s), "BK-003")


class TestRender(unittest.TestCase):
    def test_render_empty_has_all_sections(self):
        s = bl.empty_store()
        md = bl.render_md(s)
        for sec in ("## In flight", "## Next up", "## Done", "## Parked / deferred"):
            self.assertIn(sec, md)

    def test_render_item_line_shape(self):
        s = bl.empty_store()
        s["items"].append({
            "id": "BK-001",
            "section": "in_flight",
            "title": "Wire find_references",
            "ref": "handoff §lim 4",
            "probe": "grep -rn find_references",
            "verify": "cargo test",
            "tags": ["lsp"],
        })
        md = bl.render_md(s)
        self.assertIn("BK-001", md)
        self.assertIn("Wire find_references", md)
        self.assertIn("*(handoff §lim 4)*", md)
        self.assertIn("`grep -rn find_references`", md)
        self.assertIn("`cargo test`", md)
        self.assertIn("[lsp]", md)

    def test_render_done_item_shows_committed(self):
        s = bl.empty_store()
        s["items"].append({
            "id": "BK-001",
            "section": "done",
            "title": "Done thing",
            "committed": "abc1234",
            "tags": [],
        })
        md = bl.render_md(s)
        self.assertIn("[x]", md)
        self.assertIn("abc1234", md[:1500])  # in the Done section

    def test_render_parked_shows_reason(self):
        s = bl.empty_store()
        s["items"].append({
            "id": "BK-001",
            "section": "parked",
            "title": "Parked",
            "parked_reason": "needs more research",
            "tags": [],
        })
        md = bl.render_md(s)
        self.assertIn("parked: needs more research", md)

    def test_render_decisions_section(self):
        s = bl.empty_store()
        s["decisions"].append({"date": "2026-05-11", "text": "JSON is source", "why": "drift detection"})
        md = bl.render_md(s)
        self.assertIn("## Decisions", md)
        self.assertIn("JSON is source", md)
        self.assertIn("drift detection", md)


class TestRoundTrip(unittest.TestCase):
    def test_save_load_preserves_data(self):
        s = bl.empty_store()
        s["items"].append({
            "id": "BK-001",
            "section": "next_up",
            "title": "round-trip",
            "ref": None,
            "probe": "p",
            "verify": "v",
            "tags": ["a", "b"],
            "created": "2026-05-11",
            "started_at": None,
            "committed": None,
            "committed_at": None,
            "parked_reason": None,
            "probe_output": None,
        })
        s["decisions"].append({"date": "2026-05-11", "text": "x", "why": "y"})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            p = Path(f.name)
        try:
            bl.save_store(p, s)
            s2 = bl.load_store(p)
            self.assertEqual(len(s2["items"]), 1)
            self.assertEqual(s2["items"][0]["title"], "round-trip")
            self.assertEqual(s2["items"][0]["tags"], ["a", "b"])
            self.assertEqual(len(s2["decisions"]), 1)
        finally:
            p.unlink()


class TestFmtItem(unittest.TestCase):
    def test_in_flight_item_unchecked(self):
        it = {"id": "BK-001", "section": "in_flight", "title": "X", "tags": []}
        line = bl.fmt_item(it)
        self.assertTrue(line.startswith("- [ ] **BK-001**"))

    def test_done_item_checked(self):
        it = {"id": "BK-002", "section": "done", "title": "Y", "tags": []}
        line = bl.fmt_item(it)
        self.assertTrue(line.startswith("- [x] **BK-002**"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
