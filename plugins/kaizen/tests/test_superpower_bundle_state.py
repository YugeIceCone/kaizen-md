"""Tests for `kaizen-bundle state` + `kaizen-bundle tasks` — docs-state tracker.

Per user 2026-05-18 sid 32bad1f7 — "work on the new docs system have it
generate and maintain a state file + task list tracker with metadata
for /.kaizen/superpowers/".

Scope (v1):
  - `kaizen-bundle state [--apply] [--json]`
      scans .kaizen/superpowers/, writes .state.json under root, returns
      per-bundle + per-file metadata (kind, status, size, mtime).
      Dry-run by default; --apply writes .state.json.
  - `kaizen-bundle tasks [--bundle X] [--status S]`
      task-list view of non-shipped items, filterable.
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
_BUNDLE = _KZ / "scripts/util/superpower_bundle.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import superpower_bundle as _sb  # noqa: E402

# ─── _classify_kind — pure ────────────────────────────────────────────

class TestClassifyKind(unittest.TestCase):
    def test_plan_prefix(self):
        self.assertEqual(_sb._classify_kind("plan-path-restructure.md"), "plan")

    def test_spec_prefix(self):
        self.assertEqual(_sb._classify_kind("spec-observer-design.md"), "spec")

    def test_brainstorm_prefix(self):
        self.assertEqual(_sb._classify_kind("brainstorm-handoff.md"), "brainstorm")

    def test_audit_prefix(self):
        self.assertEqual(_sb._classify_kind("audit-heartbeat.md"), "audit")

    def test_notes_prefix(self):
        self.assertEqual(_sb._classify_kind("notes-thoughts.md"), "notes")

    def test_readme(self):
        self.assertEqual(_sb._classify_kind("README.md"), "README")

    def test_jsonl_data(self):
        self.assertEqual(_sb._classify_kind("plan-coverage-ideas.jsonl"), "data")

    def test_unknown_falls_back_to_other(self):
        self.assertEqual(_sb._classify_kind("misc.md"), "other")

# ─── _extract_status — pure ────────────────────────────────────────────

class TestExtractStatus(unittest.TestCase):
    def test_shipped_marker(self):
        text = "# Title\n\n**COMPLETE 2026-05-12** — landed in daddffd"
        self.assertEqual(_sb._extract_status(text), "shipped")

    def test_state_field(self):
        text = "# Title\n\n## Status\n- **State:** draft\n"
        self.assertEqual(_sb._extract_status(text), "draft")

    def test_in_progress(self):
        text = "# Title\n\n## Status\n- **State:** in-progress (Phase 2 mid-flight)"
        self.assertEqual(_sb._extract_status(text), "in-progress")

    def test_superseded(self):
        text = "# Old\n\nSUPERSEDED by newer-plan.md"
        self.assertEqual(_sb._extract_status(text), "superseded")

    def test_deferred(self):
        text = "# X\n\n**DEFERRED** until consumer exists"
        self.assertEqual(_sb._extract_status(text), "deferred")

    def test_unknown_when_no_marker(self):
        text = "# X\n\nJust some random content with no status."
        self.assertEqual(_sb._extract_status(text), "unknown")

    def test_only_scans_first_window(self):
        # Status marker must be near the top — buried at line 200 shouldn't count
        text = "intro\n" * 200 + "**COMPLETE**\n"
        self.assertEqual(_sb._extract_status(text), "unknown")

    def test_status_alias_for_state_field(self):
        # Some plans use **Status:** instead of **State:** — both should match
        text = "# Title\n\n**Status:** drafting\n"
        self.assertEqual(_sb._extract_status(text), "draft")

    def test_status_alias_in_progress(self):
        text = "# Title\n\n**Status:** in-progress\n"
        self.assertEqual(_sb._extract_status(text), "in-progress")

class TestReadmeIsReference(unittest.TestCase):
    """READMEs are folder-descriptions, not work items. They should
    classify as `reference` status so they never appear in task lists."""

    def test_readme_filename_with_no_content_is_reference(self):
        # README.md gets a special pass — no need for explicit Status marker
        status = _sb._extract_status_for_file("README.md", "# Some folder\n")
        self.assertEqual(status, "reference")

    def test_other_files_use_content_detection(self):
        # Non-README files still go through content scan
        status = _sb._extract_status_for_file("plan-x.md", "# X\n\n**COMPLETE**")
        self.assertEqual(status, "shipped")

# ─── _scan_state — pure-ish (reads filesystem) ────────────────────────

class TestScanState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "superpowers"
        self.root.mkdir()
        # Bundle 1: 2 files
        b1 = self.root / "2026-05-17-kaizen-md"
        b1.mkdir()
        (b1 / "README.md").write_text("# Bundle README\n")
        (b1 / "plan-x.md").write_text("# X plan\n\n**COMPLETE** — landed abc1234")
        # Bundle 2: 1 file
        b2 = self.root / "2026-05-18-kaizen-md-9f4c8972"
        b2.mkdir()
        (b2 / "audit-y.md").write_text("# Y audit\n\n## Status\n- **State:** draft\n")
        # Top-level file (not a bundle)
        (self.root / "README.md").write_text("# top README\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_returns_bundles_and_totals(self):
        state = _sb._scan_state(self.root)
        self.assertIn("bundles", state)
        self.assertIn("totals", state)
        # 2 bundles detected (top-level README excluded — not a dir)
        self.assertEqual(len(state["bundles"]), 2)

    def test_bundle_summary_counts_by_status(self):
        state = _sb._scan_state(self.root)
        b1 = state["bundles"]["2026-05-17-kaizen-md"]
        # 1 shipped + 1 README (now classified `reference` post-refinement)
        statuses = b1["summary"]["by_status"]
        self.assertEqual(statuses.get("shipped"), 1)
        self.assertEqual(statuses.get("reference"), 1)

    def test_totals_aggregate(self):
        state = _sb._scan_state(self.root)
        t = state["totals"]
        # 2 bundles, 3 files total (excluding root README)
        self.assertEqual(t["bundles"], 2)
        self.assertEqual(t["files"], 3)

    def test_file_entry_carries_metadata(self):
        state = _sb._scan_state(self.root)
        files = state["bundles"]["2026-05-17-kaizen-md"]["files"]
        plan = next(f for f in files if f["name"] == "plan-x.md")
        self.assertEqual(plan["kind"], "plan")
        self.assertEqual(plan["status"], "shipped")
        self.assertGreater(plan["size_bytes"], 0)

# ─── state CLI ────────────────────────────────────────────────────────

class TestStateCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "superpowers"
        self.root.mkdir()
        b1 = self.root / "2026-05-17-kaizen-md"
        b1.mkdir()
        (b1 / "plan-x.md").write_text("# X\n\n**COMPLETE**\n")
        (b1 / "plan-y.md").write_text("# Y\n\n## Status\n- **State:** draft\n")
        # Sandbox
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("KAIZEN_SUPERPOWERS_DIR", None)
        else:
            os.environ["KAIZEN_SUPERPOWERS_DIR"] = self._orig
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_BUNDLE), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_state_dry_run_no_file_written(self):
        r = self._run("state")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Dry run — .state.json not written
        self.assertFalse((self.root / ".state.json").exists())

    def test_state_apply_writes_state_json(self):
        r = self._run("state", "--apply")
        self.assertEqual(r.returncode, 0, r.stderr)
        sf = self.root / ".state.json"
        self.assertTrue(sf.is_file())
        data = json.loads(sf.read_text())
        self.assertIn("bundles", data)

    def test_state_json_output(self):
        r = self._run("state", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("totals", data)

# ─── tasks CLI ────────────────────────────────────────────────────────

class TestTasksCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "superpowers"
        self.root.mkdir()
        b1 = self.root / "2026-05-17-kaizen-md"
        b1.mkdir()
        (b1 / "plan-shipped.md").write_text("# X\n\n**COMPLETE**\n")
        (b1 / "plan-pending.md").write_text("# Y\n\n## Status\n- **State:** draft\n")
        (b1 / "plan-deferred.md").write_text("# Z\n\n**DEFERRED**\n")
        self._orig = os.environ.get("KAIZEN_SUPERPOWERS_DIR")
        os.environ["KAIZEN_SUPERPOWERS_DIR"] = str(self.root)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("KAIZEN_SUPERPOWERS_DIR", None)
        else:
            os.environ["KAIZEN_SUPERPOWERS_DIR"] = self._orig
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_BUNDLE), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )

    def test_tasks_excludes_shipped(self):
        r = self._run("tasks", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        names = [t["name"] for t in data["tasks"]]
        self.assertNotIn("plan-shipped.md", names)
        self.assertIn("plan-pending.md", names)

    def test_tasks_filter_by_status(self):
        r = self._run("tasks", "--status", "deferred", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        names = [t["name"] for t in data["tasks"]]
        self.assertEqual(names, ["plan-deferred.md"])

    def test_tasks_default_excludes_reference_readmes(self):
        # Add a README — it must NOT appear in default tasks output
        (self.root / "2026-05-17-kaizen-md" / "README.md").write_text(
            "# Bundle README\n")
        r = self._run("tasks", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        names = [t["name"] for t in data["tasks"]]
        self.assertNotIn("README.md", names)

    def test_tasks_human_output(self):
        r = self._run("tasks")
        self.assertEqual(r.returncode, 0)
        # Lists pending + deferred (excludes shipped)
        self.assertIn("plan-pending.md", r.stdout)
        self.assertIn("plan-deferred.md", r.stdout)
        self.assertNotIn("plan-shipped.md", r.stdout)

if __name__ == "__main__":
    unittest.main()
