"""Phase 2 — tests for gold_mine mechanical filter / normalize / dedup.

Pure logic tests against realistic synthetic events.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import gold_mine  # noqa: E402

class TestFilterEvents(unittest.TestCase):
    """`_filter_events` keeps:
      - evt_type in the signal-bearing allowlist
      - any event with a non-empty payload.error
    Skips:
      - events where tool_name == 'kaizen-gold' (anti-recursion)
    """

    def test_keeps_context_warn_red(self):
        events = [{"evt_type": "context.warn.red", "payload": {"pct": 92}}]
        self.assertEqual(gold_mine._filter_events(events), events)

    def test_keeps_context_warn_yellow(self):
        events = [{"evt_type": "context.warn.yellow", "payload": {"pct": 78}}]
        self.assertEqual(gold_mine._filter_events(events), events)

    def test_keeps_gold_bash_gate_warn(self):
        events = [{"evt_type": "gold.bash_gate.warn", "payload": {}}]
        self.assertEqual(gold_mine._filter_events(events), events)

    def test_keeps_handoff_auto_finalize_complete(self):
        events = [{"evt_type": "handoff.auto-finalize.complete",
                    "payload": {}}]
        self.assertEqual(gold_mine._filter_events(events), events)

    def test_keeps_auto_handoff_requested(self):
        events = [{"evt_type": "auto_handoff.requested", "payload": {}}]
        self.assertEqual(gold_mine._filter_events(events), events)

    def test_keeps_any_event_with_payload_error(self):
        events = [{"evt_type": "tool.use",
                    "payload": {"error": "ENOENT: no such file"}}]
        self.assertEqual(len(gold_mine._filter_events(events)), 1)

    def test_drops_random_events(self):
        events = [
            {"evt_type": "SessionStart"},
            {"evt_type": "Stop", "payload": {}},
            {"evt_type": "tool.use", "payload": {"ok": True}},
        ]
        self.assertEqual(gold_mine._filter_events(events), [])

    def test_anti_recursion_drops_kaizen_gold_events(self):
        events = [
            {"evt_type": "gold.captured", "tool_name": "kaizen-gold",
             "payload": {"id": 1}},
            {"evt_type": "gold.auto_captured", "tool_name": "kaizen-gold"},
            {"evt_type": "context.warn.red", "payload": {"pct": 95}},
        ]
        out = gold_mine._filter_events(events)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["evt_type"], "context.warn.red")

class TestNormalize(unittest.TestCase):
    """`_normalize` strips volatile substrings to produce a stable template.
    Strips:
      - ISO timestamps (`2026-05-17T15:00:00Z`)
      - UUIDs (8-4-4-4-12)
      - `/tmp/[^/]+/` paths
      - line numbers (`:NNN`)
    """

    def test_strips_iso_timestamp(self):
        s = "2026-05-17T15:00:00Z error at module"
        self.assertNotIn("2026-05-17", gold_mine._normalize(s))

    def test_strips_uuid(self):
        s = "session 4387fcdb-82fe-4075-ac13-325811b6576f died"
        self.assertNotIn("4387fcdb", gold_mine._normalize(s))

    def test_strips_tmp_paths(self):
        s = "wrote to /tmp/pytest-abc123/cache/file.json"
        out = gold_mine._normalize(s)
        self.assertNotIn("pytest-abc123", out)

    def test_strips_line_numbers(self):
        s = "ParseError at gold.py:123 in fn"
        out = gold_mine._normalize(s)
        self.assertNotIn(":123", out)

    def test_is_idempotent(self):
        s = "ParseError at gold.py:123 at 2026-05-17T15:00:00Z"
        n1 = gold_mine._normalize(s)
        n2 = gold_mine._normalize(n1)
        self.assertEqual(n1, n2)

class TestDedup(unittest.TestCase):
    """`_dedup_templates` keeps:
      - templates not seen in `history`
      - OR templates with recurrence_count ≥ 2 in the new batch.
    Returns list of (template, occurrences) tuples for downstream use.
    """

    def test_first_occurrence_kept(self):
        batch = ["template-a", "template-b"]
        history = set()
        out = gold_mine._dedup_templates(batch, history=history)
        self.assertEqual(len(out), 2)

    def test_recurrent_in_batch_kept_even_if_in_history(self):
        batch = ["t-x", "t-x", "t-x"]  # 3 occurrences
        history = {"t-x"}  # already seen
        out = gold_mine._dedup_templates(batch, history=history)
        # Recurrence ≥ 2 → keep with the recurrence count.
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], "t-x")
        self.assertEqual(out[0][1], 3)

    def test_single_occurrence_in_history_dropped(self):
        batch = ["seen-before"]
        history = {"seen-before"}
        out = gold_mine._dedup_templates(batch, history=history)
        self.assertEqual(out, [])

    def test_dedups_within_batch_for_new_templates(self):
        batch = ["new", "new", "new"]
        history = set()
        out = gold_mine._dedup_templates(batch, history=history)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], 3)

class TestEventToTemplate(unittest.TestCase):
    """`event_to_template(evt)` returns the normalized template string used
    for dedup — combines evt_type + payload signal."""

    def test_template_stable_across_timestamps(self):
        e1 = {"evt_type": "context.warn.red",
              "payload": {"pct": 92, "ts": "2026-05-17T10:00:00Z"}}
        e2 = {"evt_type": "context.warn.red",
              "payload": {"pct": 92, "ts": "2026-05-17T15:00:00Z"}}
        self.assertEqual(gold_mine.event_to_template(e1),
                          gold_mine.event_to_template(e2))

if __name__ == "__main__":
    unittest.main()
