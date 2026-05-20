"""Tests for kaizen-spec-driven — EARS lint + confidence score + gate.

Run:
    python3 -m unittest tests.test_spec_driven -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "scripts" / "spec_driven"
sys.path.insert(0, str(SCRIPTS))

import _ears  # noqa: E402
import _gate  # noqa: E402


# ─── EARS linter ────────────────────────────────────────────────────────

class TestEarsLint(unittest.TestCase):

    def test_ubiquitous_pattern_passes(self):
        text = "- **REQ-001** THE SYSTEM SHALL emit one event per tool call."
        r = _ears.lint_requirements(text)
        self.assertTrue(r["ok"])
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["by_pattern"]["ubiquitous"], 1)

    def test_event_driven_pattern_passes(self):
        text = "- **REQ-002** WHEN a tool call completes, THE SYSTEM SHALL log the result."
        r = _ears.lint_requirements(text)
        self.assertTrue(r["ok"])
        self.assertEqual(r["by_pattern"]["event_driven"], 1)

    def test_state_driven_pattern_passes(self):
        text = "- **REQ-003** WHILE the daemon is running, THE SYSTEM SHALL flush every 60s."
        r = _ears.lint_requirements(text)
        self.assertTrue(r["ok"])
        self.assertEqual(r["by_pattern"]["state_driven"], 1)

    def test_unwanted_pattern_passes(self):
        text = "- **REQ-004** IF the disk is full, THEN THE SYSTEM SHALL refuse new writes."
        r = _ears.lint_requirements(text)
        self.assertTrue(r["ok"])
        self.assertEqual(r["by_pattern"]["unwanted"], 1)

    def test_optional_pattern_passes(self):
        text = "- **REQ-005** WHERE caching is enabled, THE SYSTEM SHALL hit cache first."
        r = _ears.lint_requirements(text)
        self.assertTrue(r["ok"])
        self.assertEqual(r["by_pattern"]["optional"], 1)

    def test_placeholder_flagged(self):
        text = "- **REQ-001** WHEN <trigger>, THE SYSTEM SHALL <behavior>."
        r = _ears.lint_requirements(text)
        self.assertFalse(r["ok"])
        self.assertEqual(r["violations"][0]["reason"],
                         "unfilled placeholder (<...>)")

    def test_non_ears_clause_flagged(self):
        text = "- **REQ-001** The system should be fast and easy to use."
        r = _ears.lint_requirements(text)
        self.assertFalse(r["ok"])
        self.assertEqual(r["violations"][0]["reason"],
                         "does not match any EARS pattern")

    def test_non_req_lines_ignored(self):
        text = "## Functional requirements\n\nSome prose here.\n\n- bullet point\n"
        r = _ears.lint_requirements(text)
        self.assertEqual(r["total"], 0)


# ─── Confidence score ───────────────────────────────────────────────────

class TestConfidenceScore(unittest.TestCase):

    def test_high_score_for_clean_ears(self):
        text = """
- **REQ-001** WHEN a tool call returns rc != 0, THE SYSTEM SHALL log the failure within 100ms.
- **REQ-002** WHILE the daemon is running, THE SYSTEM SHALL flush events every 60s.
- **REQ-003** IF the queue exceeds 1000 entries, THEN THE SYSTEM SHALL drop oldest.
"""
        r = _ears.score_requirements(text)
        self.assertGreater(r["score"], 80)
        self.assertIn("branch_high", r["advisory"])

    def test_low_score_with_placeholders(self):
        text = """
- **REQ-001** WHEN <trigger>, THE SYSTEM SHALL <behavior>.
- **REQ-002** THE SYSTEM SHALL <invariant>.
- **REQ-003** IF <error condition>, THEN THE SYSTEM SHALL <recovery response>.
"""
        r = _ears.score_requirements(text)
        self.assertLess(r["score"], 50)

    def test_zero_when_no_reqs(self):
        r = _ears.score_requirements("# title\n\nSome prose\n")
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["signals"]["total_reqs"], 0)

    def test_ambiguous_words_dock_score(self):
        clean = """
- **REQ-001** THE SYSTEM SHALL respond within 100ms.
- **REQ-002** WHEN the cache misses, THE SYSTEM SHALL fetch in <50ms.
"""
        ambiguous = """
- **REQ-001** THE SYSTEM SHALL respond fast.
- **REQ-002** WHEN the cache misses, THE SYSTEM SHALL fetch as needed.
"""
        s_clean = _ears.score_requirements(clean)["score"]
        s_amb = _ears.score_requirements(ambiguous)["score"]
        self.assertGreater(s_clean, s_amb)


# ─── Phase-gate verifier ────────────────────────────────────────────────

# Reach into the blueprint module to write test plans
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "blueprint"))
import _blueprint as bp  # noqa: E402


class TestGate(unittest.TestCase):

    def _plan(self, items):
        return {
            "$schema": "https://kaizen-md/templates/planning-blueprint/blueprint.schema.json",
            "blueprint_version": "1",
            "project": "test",
            "items": items,
        }

    def test_gate_passes_on_shipped_item(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(self._plan([
                {"id": "01", "kind": "plan", "title": "Phase 1",
                 "status": "draft", "links": {}},
            ])))
            bp.set_item_status(p, "01", "shipped")  # injects hash
            r = _gate.gate_check(p, "01")
            self.assertTrue(r["ok"])
            self.assertEqual(r["item_status"], "shipped")

    def test_gate_blocks_on_draft_item(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(self._plan([
                {"id": "01", "kind": "plan", "title": "Phase 1",
                 "status": "draft", "links": {}},
            ])))
            bp.set_item_status(p, "01", "draft")  # no-op; injects hash
            r = _gate.gate_check(p, "01")
            self.assertFalse(r["ok"])
            self.assertIn("expected", r["reason"])

    def test_gate_blocks_on_hash_drift(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(self._plan([
                {"id": "01", "kind": "plan", "title": "Phase 1",
                 "status": "shipped", "links": {}},
            ])))
            bp.set_item_status(p, "01", "shipped")  # injects hash
            # External mutation bypassing the CLI
            raw = json.loads(p.read_text())
            raw["items"][0]["title"] = "TAMPERED"
            p.write_text(json.dumps(raw))
            r = _gate.gate_check(p, "01")
            self.assertFalse(r["ok"])
            self.assertIn("drift", r["reason"].lower())

    def test_gate_unfinished_tasks_block(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(self._plan([
                {"id": "07", "kind": "task-list", "title": "L",
                 "status": "shipped", "links": {},
                 "tasks": [
                     {"id": "07.1", "subject": "A", "status": "completed"},
                     {"id": "07.2", "subject": "B", "status": "pending"},
                 ]},
            ])))
            bp.set_item_status(p, "07", "shipped")  # injects hash
            r = _gate.gate_check(p, "07", require_all_tasks_completed=True)
            self.assertFalse(r["ok"])
            self.assertIn("pending=1", r["reason"])

    def test_gate_missing_item(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "plan.json"
            p.write_text(json.dumps(self._plan([])))
            r = _gate.gate_check(p, "99")
            self.assertFalse(r["ok"])
            self.assertIn("not found", r["reason"])


if __name__ == "__main__":
    unittest.main()
