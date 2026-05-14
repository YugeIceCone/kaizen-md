"""Tests for roadmap_status.py — parse + render phase-progress tables
from a handoff markdown.

Run:
    python3 -m unittest tests.test_roadmap_status -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))

import roadmap_status as rs  # noqa: E402


SAMPLE_HANDOFF = """# Handoff

## Phase 1 — example phase

| # | Item | File(s) | Status |
|---|---|---|---|
| A | First thing | `a.py` | ✅ done (`abc1234`) |
| B | Second thing | `b.py` | ✅ done (`def5678`) |
| C | Third thing | `c.py` | ⬜ pending |

## Phase 2 — next phase

| # | Item | File(s) | Status |
|---|---|---|---|
| X | Big feature | `x.py` | ⬜ pending |
| Y | Another | `y.py` | ⬜ pending |

## Some other section

Not a phase table.

## Phase 3 — speculative

| # | Item | Status |
|---|---|---|
| Z | Speculative item | ⬜ pending |
"""


def _write_handoff(tmp: Path, body: str = SAMPLE_HANDOFF) -> Path:
    plans = tmp / "plans"
    plans.mkdir(exist_ok=True)
    p = plans / "2026-05-13-handoff.md"
    p.write_text(body)
    return p


class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)
        # Clear env override that other tests might have set
        self._saved_env = os.environ.pop("KAIZEN_ROADMAP_HANDOFF", None)

    def tearDown(self):
        os.chdir(self._cwd)
        if self._saved_env is not None:
            os.environ["KAIZEN_ROADMAP_HANDOFF"] = self._saved_env
        self._tmpcm.cleanup()


# ─── Handoff resolution ──────────────────────────────────────────────


class TestResolveHandoff(_CwdMixin, unittest.TestCase):
    def test_returns_none_when_no_plans_dir(self):
        self.assertIsNone(rs.resolve_handoff_path())

    def test_finds_handoff_in_plans(self):
        _write_handoff(self.tmp)
        p = rs.resolve_handoff_path()
        self.assertIsNotNone(p)
        self.assertTrue(p.name.endswith(".md"))

    def test_env_override_wins(self):
        custom = self.tmp / "elsewhere.md"
        custom.write_text(SAMPLE_HANDOFF)
        os.environ["KAIZEN_ROADMAP_HANDOFF"] = str(custom)
        try:
            self.assertEqual(rs.resolve_handoff_path(), custom.resolve())
        finally:
            del os.environ["KAIZEN_ROADMAP_HANDOFF"]


# ─── Parser ───────────────────────────────────────────────────────────


class TestParsePhases(unittest.TestCase):
    def test_finds_all_phases_with_tables(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        numbers = [p.number for p in phases]
        self.assertEqual(numbers, [1, 2, 3])

    def test_extracts_titles(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        self.assertEqual(phases[0].title, "example phase")
        self.assertEqual(phases[1].title, "next phase")

    def test_classifies_done_vs_pending(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        p1 = phases[0]
        self.assertEqual(p1.done, 2)
        self.assertEqual(p1.total, 3)

    def test_extracts_commit_sha_when_present(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        done_items = [it for it in phases[0].items if it.status == "done"]
        self.assertEqual(done_items[0].commit, "abc1234")
        self.assertEqual(done_items[1].commit, "def5678")

    def test_empty_handoff_returns_no_phases(self):
        self.assertEqual(rs.parse_phases("just prose"), [])

    def test_phases_separated_by_non_phase_section(self):
        """Sections between phase headings shouldn't merge phases."""
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        self.assertEqual(len(phases), 3)
        # Phase 3 starts AFTER the "Some other section" — make sure
        # Phase 2 doesn't capture its rows.
        p2 = next(p for p in phases if p.number == 2)
        item_ids = [it.item_id for it in p2.items]
        self.assertNotIn("Z", item_ids)


# ─── Rendering ────────────────────────────────────────────────────────


class TestRender(unittest.TestCase):
    def test_dashboard_contains_phase_lines(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        dash = rs.render_dashboard(phases)
        self.assertIn("Phase 1", dash)
        self.assertIn("Phase 2", dash)
        self.assertIn("Phase 3", dash)
        self.assertIn("Total", dash)

    def test_dashboard_shows_complete_marker_for_100_pct(self):
        phases = rs.parse_phases(
            "## Phase 9 — done\n\n"
            "| # | Item | Status |\n|---|---|---|\n"
            "| Q | only thing | ✅ done |\n"
        )
        dash = rs.render_dashboard(phases)
        self.assertIn("✅ COMPLETE", dash)

    def test_dashboard_next_up_points_at_first_pending(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        dash = rs.render_dashboard(phases)
        self.assertIn("Next up: C", dash)

    def test_dashboard_no_next_when_all_done(self):
        phases = rs.parse_phases(
            "## Phase 1 — all done\n\n"
            "| # | Item | Status |\n|---|---|---|\n"
            "| A | thing | ✅ done |\n"
        )
        dash = rs.render_dashboard(phases)
        self.assertNotIn("Next up:", dash)

    def test_bar_width(self):
        """Bars are exactly BAR_LENGTH chars."""
        bar = rs._bar(0, 10)
        self.assertEqual(len(bar), rs.BAR_LENGTH)
        bar = rs._bar(10, 10)
        self.assertEqual(len(bar), rs.BAR_LENGTH)
        bar = rs._bar(5, 10)
        self.assertEqual(len(bar), rs.BAR_LENGTH)

    def test_find_next_pending(self):
        phases = rs.parse_phases(SAMPLE_HANDOFF)
        nxt = rs.find_next_pending(phases)
        self.assertEqual(nxt.item_id, "C")

    def test_find_next_pending_none_when_complete(self):
        phases = rs.parse_phases(
            "## Phase 1 — done\n\n"
            "| # | Item | Status |\n|---|---|---|\n"
            "| A | thing | ✅ done |\n"
        )
        self.assertIsNone(rs.find_next_pending(phases))


# ─── CLI ──────────────────────────────────────────────────────────────


class TestCli(_CwdMixin, unittest.TestCase):
    HELPER = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "roadmap_status.py"

    def test_progress_subcommand_text(self):
        _write_handoff(self.tmp)
        import subprocess
        result = subprocess.run(
            ["python3", str(self.HELPER), "progress"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Phase 1", result.stdout)
        self.assertIn("Total", result.stdout)

    def test_progress_json(self):
        _write_handoff(self.tmp)
        import subprocess
        result = subprocess.run(
            ["python3", str(self.HELPER), "progress", "--json"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(len(data["phases"]), 3)
        self.assertEqual(data["next"]["item_id"], "C")

    def test_next_subcommand(self):
        _write_handoff(self.tmp)
        import subprocess
        result = subprocess.run(
            ["python3", str(self.HELPER), "next"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("C", result.stdout)

    def test_phase_subcommand_detail(self):
        _write_handoff(self.tmp)
        import subprocess
        result = subprocess.run(
            ["python3", str(self.HELPER), "phase", "2"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Phase 2", result.stdout)
        self.assertIn("Big feature", result.stdout)
        self.assertIn("Another", result.stdout)


class TestMcp(_CwdMixin, unittest.TestCase):
    def _import(self):
        # Need to force-reload roadmap_status too because it reads cwd
        for mod in ("roadmap_mcp", "roadmap_status"):
            if mod in sys.modules:
                del sys.modules[mod]
        import roadmap_mcp
        return roadmap_mcp

    def test_progress_tool(self):
        _write_handoff(self.tmp)
        m = self._import()
        out = asyncio.run(m.roadmap_progress())
        self.assertTrue(out["present"])
        self.assertEqual(len(out["phases"]), 3)
        self.assertIn("Phase 1", out["dashboard_text"])

    def test_next_tool(self):
        _write_handoff(self.tmp)
        m = self._import()
        out = asyncio.run(m.roadmap_next())
        self.assertEqual(out["item_id"], "C")

    def test_phase_tool_unknown_number(self):
        _write_handoff(self.tmp)
        m = self._import()
        out = asyncio.run(m.roadmap_phase(99))
        self.assertIn("error", out)

    def test_no_handoff_returns_present_false(self):
        m = self._import()
        out = asyncio.run(m.roadmap_progress())
        self.assertFalse(out["present"])


class TestRegistration(unittest.TestCase):
    def test_mcp_json_lists_roadmap_server(self):
        data = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
        self.assertIn("roadmap", data["mcpServers"])
        joined = " ".join(data["mcpServers"]["roadmap"]["args"])
        self.assertIn("roadmap_mcp.py", joined)


if __name__ == "__main__":
    unittest.main()
