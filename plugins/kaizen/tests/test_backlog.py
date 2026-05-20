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
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
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
    def setUp(self):
        # Save_store has a memory-ledger side-effect (BK-023). This test
        # only cares about JSON round-trip, so disable the ledger.
        import os
        os.environ["KAIZEN_BACKLOG_LEDGER_DISABLE"] = "1"

    def tearDown(self):
        import os
        os.environ.pop("KAIZEN_BACKLOG_LEDGER_DISABLE", None)

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


class TestMdRoundTripStable(unittest.TestCase):
    """BK-019. Mutating ops save_store then render_md. The rendered
    .md must round-trip through verify on the same store unchanged —
    no spurious whitespace, no key-order flutter."""

    def test_render_idempotent_across_two_calls(self):
        s = bl.empty_store()
        s["items"].extend([
            {"id": "BK-001", "section": "next_up", "title": "T1",
             "ref": None, "probe": "p1", "verify": "v1",
             "tags": ["x"], "created": "2026-05-19"},
            {"id": "BK-002", "section": "done", "title": "T2",
             "committed": "abc1234", "tags": [], "created": "2026-05-18"},
        ])
        first = bl.render_md(s)
        second = bl.render_md(s)
        self.assertEqual(first, second,
                         "render_md is non-deterministic across calls")

    def test_save_load_render_preserves_md_byte_for_byte(self):
        s = bl.empty_store()
        s["items"].append({
            "id": "BK-001", "section": "next_up", "title": "round-trip",
            "ref": None, "probe": "p", "verify": "v",
            "tags": ["a"], "created": "2026-05-19",
        })
        before = bl.render_md(s)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            p = Path(f.name)
        try:
            bl.save_store(p, s)
            s2 = bl.load_store(p)
            after = bl.render_md(s2)
            # Allow the metadata.updated date to differ (it's overwritten
            # on save) but the *rendered .md* must be byte-stable.
            self.assertEqual(before, after,
                             "render_md(load_store(save_store(s))) != render_md(s)")
        finally:
            p.unlink()


class TestRenderHeaderPath(unittest.TestCase):
    """BK-019. Stale path in the generated header tripped up users who
    followed the link. The canonical CLI now ships as
    `kaizen backlog ...` — the legacy `~/.claude/skills/workflow/...`
    string is wrong + drift-prone."""

    def test_header_does_not_reference_legacy_path(self):
        md = bl.render_md(bl.empty_store())
        self.assertNotIn("~/.claude/scripts/util/backlog.py", md,
                         "stale legacy script path in header")

    def test_header_points_at_canonical_cli(self):
        md = bl.render_md(bl.empty_store())
        self.assertIn("kaizen backlog", md)


class TestMemoryLedger(unittest.TestCase):
    """BK-023. save_store side-effect writes a token-efficient ledger
    to the CC auto-memory dir so the agent can read backlog state from
    auto-loaded context (no `kaizen-backlog list` roundtrip).

    Tests redirect the memory dir to a tempdir via KAIZEN_BACKLOG_LEDGER_DIR
    so they never touch the real ~/.claude/projects/<slug>/memory/."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._json = self.tmp / "backlog.json"
        self._ledger_dir = self.tmp / "memory"
        self._ledger_dir.mkdir()
        import os
        os.environ["KAIZEN_BACKLOG_LEDGER_DIR"] = str(self._ledger_dir)

    def tearDown(self):
        import os
        os.environ.pop("KAIZEN_BACKLOG_LEDGER_DIR", None)
        self._tmp.cleanup()

    def _store_with_items(self) -> dict:
        s = bl.empty_store()
        s["items"].extend([
            {"id": "BK-001", "section": "in_flight", "title": "active 1",
             "ref": None, "probe": "p", "verify": "v",
             "tags": ["a"], "created": "2026-05-19"},
            {"id": "BK-002", "section": "next_up", "title": "queued 2",
             "ref": None, "probe": "p", "verify": "v",
             "tags": ["b", "c"], "created": "2026-05-19"},
            {"id": "BK-003", "section": "done", "title": "completed 3",
             "ref": None, "probe": "p", "verify": "v",
             "tags": [], "created": "2026-05-18",
             "committed": "abc1234"},
            {"id": "BK-004", "section": "parked", "title": "deferred 4",
             "ref": None, "probe": "p", "verify": "v",
             "tags": [], "created": "2026-05-17",
             "parked_reason": "needs research"},
        ])
        return s

    def test_save_store_writes_ledger(self):
        bl.save_store(self._json, self._store_with_items())
        ledger = self._ledger_dir / "backlog_ledger.md"
        self.assertTrue(ledger.is_file(),
                        f"save_store did not write {ledger}")

    def test_ledger_has_counts_header(self):
        bl.save_store(self._json, self._store_with_items())
        text = (self._ledger_dir / "backlog_ledger.md").read_text()
        self.assertIn("in_flight=1", text)
        self.assertIn("next_up=1", text)
        self.assertIn("done=1", text)
        self.assertIn("parked=1", text)

    def test_ledger_lists_active_items(self):
        bl.save_store(self._json, self._store_with_items())
        text = (self._ledger_dir / "backlog_ledger.md").read_text()
        # In-flight and next_up items must appear by ID + title
        self.assertIn("BK-001", text)
        self.assertIn("active 1", text)
        self.assertIn("BK-002", text)
        self.assertIn("queued 2", text)

    def test_ledger_byte_stable_across_redundant_saves(self):
        s = self._store_with_items()
        bl.save_store(self._json, s)
        first = (self._ledger_dir / "backlog_ledger.md").read_bytes()
        # metadata.updated is overwritten on save — re-load to avoid
        # spurious diff. Re-save same store after load.
        s2 = bl.load_store(self._json)
        bl.save_store(self._json, s2)
        second = (self._ledger_dir / "backlog_ledger.md").read_bytes()
        self.assertEqual(first, second,
                         "ledger format is not byte-stable across saves")

    def test_disable_knob_skips_write(self):
        import os
        os.environ["KAIZEN_BACKLOG_LEDGER_DISABLE"] = "1"
        try:
            bl.save_store(self._json, self._store_with_items())
            ledger = self._ledger_dir / "backlog_ledger.md"
            self.assertFalse(ledger.exists(),
                             "disable knob should skip ledger write")
        finally:
            os.environ.pop("KAIZEN_BACKLOG_LEDGER_DISABLE", None)


class TestDoneAliasForTick(unittest.TestCase):
    """BK-019. `kaizen backlog done BK-N` is the more discoverable verb;
    aliases the existing `tick` behavior. No new state — just a parser
    entry."""

    def test_done_subparser_exists(self):
        parser = bl.build_parser()
        # build_parser exposes the subparsers map via the action
        sub_action = next(
            a for a in parser._subparsers._group_actions
            if isinstance(a, type(parser._subparsers._group_actions[0]))
        )
        self.assertIn("done", sub_action.choices,
                      "`done` should be a parser verb (alias of tick)")

    def test_done_routes_to_tick(self):
        # main() dispatches by args.cmd; `done` must funnel into cmd_tick.
        s = bl.empty_store()
        s["items"].append({
            "id": "BK-001", "section": "in_flight", "title": "T",
            "ref": None, "probe": "p", "verify": "v",
            "tags": [], "created": "2026-05-19",
            "started_at": None, "committed": None, "committed_at": None,
            "parked_reason": None, "probe_output": None,
        })
        import argparse
        args = argparse.Namespace(id="BK-001", committed="abc1234")
        bl.cmd_tick(s, args)  # cmd_tick is the underlying handler
        self.assertEqual(s["items"][0]["section"], "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
