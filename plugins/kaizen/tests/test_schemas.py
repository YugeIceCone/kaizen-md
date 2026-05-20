#!/usr/bin/env python3
"""Unit tests for scripts/schemas.py — dataclass round-trips + validation."""

from __future__ import annotations

import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import schemas  # noqa: E402

class TestTraceEvent(unittest.TestCase):
    def test_minimal(self):
        e = schemas.TraceEvent(ts="2026-05-12T00:00:00.000Z", src="hook", evt="X")
        self.assertEqual(e.validate(), [])

    def test_full(self):
        e = schemas.TraceEvent(
            ts="2026-05-12T00:00:00.000Z", src="llm", evt="call",
            sid="sid-1", tool="Bash", ms=42, data={"model": "claude-opus-4-7"},
        )
        self.assertEqual(e.validate(), [])
        d = e.to_jsonl_dict()
        self.assertEqual(d["model" if False else "data"]["model"], "claude-opus-4-7")
        self.assertNotIn("sid", schemas.TraceEvent(ts="x", src="hook", evt="x").to_jsonl_dict())

    def test_invalid_src(self):
        e = schemas.TraceEvent(ts="x", src="bogus", evt="x")
        errs = e.validate()
        self.assertTrue(any("invalid src" in s for s in errs))

    def test_empty_evt_invalid(self):
        e = schemas.TraceEvent(ts="x", src="hook", evt="")
        self.assertIn("evt is required (non-empty)", e.validate())

    def test_negative_ms_invalid(self):
        e = schemas.TraceEvent(ts="x", src="hook", evt="x", ms=-5)
        self.assertTrue(any("ms must be >=0" in s for s in e.validate()))

    def test_from_dict_tolerates_extra(self):
        e = schemas.from_dict(schemas.TraceEvent, {
            "ts": "x", "src": "hook", "evt": "x",
            "future_field": "ignored",
        })
        self.assertEqual(e.evt, "x")

    def test_from_dict_tolerates_missing(self):
        e = schemas.from_dict(schemas.TraceEvent, {"ts": "x", "src": "hook", "evt": "x"})
        self.assertEqual(e.sid, "")
        self.assertEqual(e.tool, "")
        self.assertIsNone(e.ms)

class TestInboxMessage(unittest.TestCase):
    def test_round_trip(self):
        m = schemas.InboxMessage(ts="2026-05-12T00:00:00Z", prompt="hi")
        d = m.to_dict()
        m2 = schemas.from_dict(schemas.InboxMessage, d)
        self.assertEqual(m2.prompt, "hi")
        self.assertFalse(m2.drained)

    def test_drained_with_reason(self):
        m = schemas.InboxMessage(
            ts="x", prompt="p", drained=True,
            drained_at="y", drain_reason="turn-starter-completed",
        )
        self.assertEqual(m.drain_reason, "turn-starter-completed")

class TestDaemonState(unittest.TestCase):
    def test_defaults(self):
        s = schemas.DaemonState()
        self.assertEqual(s.runs, 0)
        self.assertEqual(s.actions, {})

    def test_round_trip(self):
        s = schemas.DaemonState(
            runs=5, last_run="2026-05-12T00:00:00Z",
            source_hash="abc", actions={"refresh-cache": 3},
        )
        d = s.to_dict()
        s2 = schemas.from_dict(schemas.DaemonState, d)
        self.assertEqual(s2.runs, 5)
        self.assertEqual(s2.actions["refresh-cache"], 3)

class TestBacklogItem(unittest.TestCase):
    def test_minimal(self):
        b = schemas.BacklogItem(id="BK-001", title="x")
        self.assertEqual(b.section, "next_up")
        self.assertEqual(b.tags, [])

    def test_full_lifecycle(self):
        b = schemas.BacklogItem(
            id="BK-042", title="ship feature", section="done",
            probe="grep ...", verify="cargo test", ref="quote",
            tags=["feat", "rust"],
            created="2026-05-01T00:00:00Z",
            started="2026-05-02T00:00:00Z",
            completed="2026-05-03T00:00:00Z",
            committed_sha="abc1234",
        )
        d = asdict(b)
        b2 = schemas.from_dict(schemas.BacklogItem, d)
        self.assertEqual(b2.committed_sha, "abc1234")
        self.assertEqual(b2.tags, ["feat", "rust"])

class TestBacklogStore(unittest.TestCase):
    def test_empty(self):
        s = schemas.BacklogStore()
        self.assertEqual(s.schema_version, 1)
        self.assertEqual(s.kind, "kaizen.backlog")
        self.assertEqual(s.items, [])

    def test_with_decisions(self):
        s = schemas.BacklogStore()
        s.decisions.append(asdict(schemas.BacklogDecision(text="X", why="Y")))
        self.assertEqual(len(s.decisions), 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
