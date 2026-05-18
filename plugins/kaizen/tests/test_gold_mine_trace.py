"""Phase C — trace stream wired into gold_mine.

Companion to test_gold_mine_pipeline.py (dxm path). Verifies:
  - _trace_path() respects KAIZEN_TRACE_DIR env override
  - _normalize_trace_event() translates trace shape → dxm shape
  - run_mine() reads from trace events.jsonl alongside dxm events
  - cursor.trace key advances after a successful trace scan
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills" / "workflow" / "scripts"))

import gold_mine  # noqa: E402


class TraceBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.kaizen_dir = self.tmp / "kz"
        self.kaizen_dir.mkdir()
        self.slug = "-trace-test"
        self.gold_dir = self.kaizen_dir / "gold" / self.slug
        self.gold_dir.mkdir(parents=True)
        self.dxm_dir = self.kaizen_dir / "dxm"
        self.dxm_dir.mkdir()
        self.trace_dir = self.kaizen_dir / "trace"
        self.trace_dir.mkdir()

        self._orig = {k: os.environ.get(k) for k in
                       ("KAIZEN_DIR", "KAIZEN_DXM_DIR", "KAIZEN_TRACE_DIR",
                        "KAIZEN_PROJECT_SLUG", "KAIZEN_GOLD_FILE",
                        "KAIZEN_GOLD_MINE_ENABLE")}
        os.environ["KAIZEN_DIR"]            = str(self.kaizen_dir)
        os.environ["KAIZEN_DXM_DIR"]        = str(self.dxm_dir)
        os.environ["KAIZEN_TRACE_DIR"]      = str(self.trace_dir)
        os.environ["KAIZEN_PROJECT_SLUG"]   = self.slug
        os.environ["KAIZEN_GOLD_FILE"]      = str(self.gold_dir / "patterns.jsonl")
        # Intentionally NOT setting KAIZEN_GOLD_MINE_ENABLE=1 — Ollama
        # scoring is gated off so urllib.urlopen calls don't add ~1s
        # per test. Tests assert on scan / cursor state, not score
        # outcomes; the unscored count covers the no-LLM path.
        os.environ.pop("KAIZEN_GOLD_MINE_ENABLE", None)

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _seed_trace(self, events: list[dict]) -> Path:
        p = self.trace_dir / "events.jsonl"
        with p.open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return p


class TestTracePath(unittest.TestCase):
    def test_env_override(self):
        with patch.dict(os.environ, {"KAIZEN_TRACE_DIR": "/tmp/xyz"}, clear=False):
            p = gold_mine._trace_path()
            self.assertEqual(p, Path("/tmp/xyz/events.jsonl"))

    def test_default_path(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KAIZEN_TRACE_DIR", None)
            p = gold_mine._trace_path()
            self.assertEqual(
                p, Path.home() / ".claude" / ".kaizen" / "indexes" / "trace" / "events.jsonl",
            )


class TestNormalizer(unittest.TestCase):
    def test_translates_trace_to_dxm_shape(self):
        e = {"evt": "PreToolUse-bash", "data": {"cmd": "ls"},
             "tool": "Bash", "sid": "abc", "ts_unix": 1700}
        n = gold_mine._normalize_trace_event(e)
        self.assertEqual(n["evt_type"], "PreToolUse-bash")
        self.assertEqual(n["payload"], {"cmd": "ls"})
        self.assertEqual(n["tool_name"], "Bash")
        self.assertEqual(n["session_id"], "abc")
        self.assertEqual(n["ts_unix"], 1700)
        self.assertEqual(n["_src"], "trace")

    def test_handles_dxm_shape_passthrough(self):
        """If someone hands a dxm-shape event to the normalizer, it
        doesn't break — keeps existing keys."""
        e = {"evt_type": "X", "payload": {}, "tool_name": "Y", "ts_unix": 0}
        n = gold_mine._normalize_trace_event(e)
        self.assertEqual(n["evt_type"], "X")
        self.assertEqual(n["tool_name"], "Y")

    def test_empty_event_safe(self):
        n = gold_mine._normalize_trace_event({})
        self.assertEqual(n["evt_type"], "")
        self.assertEqual(n["payload"], {})


class TestTraceScan(TraceBase):
    def test_run_mine_reads_trace_events(self):
        """run_mine() must pick up trace events (not just dxm)."""
        self._seed_trace([
            {"evt": "context.warn.red", "data": {"pct": 92}, "tool": "Bash",
             "sid": "s1", "ts_unix": 1700},
        ])
        summary = gold_mine.run_mine()
        self.assertGreaterEqual(summary["scanned"], 1,
                                  "trace event not scanned")

    def test_cursor_trace_key_advances_after_scan(self):
        self._seed_trace([
            {"evt": "context.warn.red", "data": {"pct": 92},
             "tool": "Bash", "sid": "s1", "ts_unix": 1700},
        ])
        gold_mine.run_mine()
        cursor = gold_mine.load_cursor()
        self.assertIn("trace", cursor, "cursor missing trace key")
        self.assertIn("events.jsonl", cursor["trace"],
                       "cursor.trace missing events.jsonl entry")
        cur_state = cursor["trace"]["events.jsonl"]
        self.assertIn("byte_offset", cur_state)
        self.assertGreater(cur_state["byte_offset"], 0)

    def test_second_run_short_circuits_on_trace(self):
        """Same mtime, same hash → no re-scan of trace events."""
        self._seed_trace([
            {"evt": "context.warn.red", "data": {"pct": 92},
             "tool": "Bash", "sid": "s1", "ts_unix": 1700},
        ])
        s1 = gold_mine.run_mine()
        s2 = gold_mine.run_mine()
        # First run sees the event; second sees nothing new
        self.assertGreaterEqual(s1["scanned"], 1)
        self.assertEqual(s2["scanned"], 0,
                          "second run re-read trace despite unchanged file")

    def test_dxm_and_trace_both_scanned_in_one_run(self):
        """Both streams contribute to the same scanned-count."""
        dxm_p = self.dxm_dir / "events-test.jsonl"
        with dxm_p.open("w") as f:
            f.write(json.dumps({"evt_type": "Stop", "payload": {},
                                  "tool_name": "Stop", "ts_unix": 1701}) + "\n")
        self._seed_trace([
            {"evt": "context.warn.red", "data": {},
             "tool": "Bash", "sid": "s", "ts_unix": 1700},
        ])
        summary = gold_mine.run_mine()
        self.assertEqual(summary["scanned"], 2,
                          f"expected dxm+trace=2; got {summary['scanned']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
