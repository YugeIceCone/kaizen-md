"""Phase 4 — full-pipeline integration tests with mocked Ollama scorer.

Stitches phases 1+2+3 together through `gold_mine.run_mine()`. Verifies
the threshold gate writes the right artifact for each score band.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import gold_mine  # noqa: E402

class PipelineBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.kaizen_dir = self.tmp / "kz"
        self.kaizen_dir.mkdir()
        self.slug = "-test-proj"
        self.gold_dir = self.kaizen_dir / "gold" / self.slug
        self.gold_dir.mkdir(parents=True)
        self.dxm_dir = self.kaizen_dir / "dxm"
        self.dxm_dir.mkdir()

        self._orig_kz = os.environ.get("KAIZEN_DIR")
        self._orig_dxm = os.environ.get("KAIZEN_DXM_DIR")
        self._orig_gold = os.environ.get("KAIZEN_GOLD_FILE")
        self._orig_slug = os.environ.get("KAIZEN_PROJECT_SLUG")
        self._orig_enable = os.environ.get("KAIZEN_GOLD_MINE_ENABLE")

        os.environ["KAIZEN_DIR"]            = str(self.kaizen_dir)
        os.environ["KAIZEN_DXM_DIR"]        = str(self.dxm_dir)
        os.environ["KAIZEN_PROJECT_SLUG"]   = self.slug
        os.environ["KAIZEN_GOLD_FILE"]      = str(self.gold_dir / "patterns.jsonl")
        os.environ["KAIZEN_GOLD_MINE_ENABLE"] = "1"

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in [("KAIZEN_DIR", self._orig_kz),
                     ("KAIZEN_DXM_DIR", self._orig_dxm),
                     ("KAIZEN_GOLD_FILE", self._orig_gold),
                     ("KAIZEN_PROJECT_SLUG", self._orig_slug),
                     ("KAIZEN_GOLD_MINE_ENABLE", self._orig_enable)]:
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _seed_events(self, events):
        p = self.dxm_dir / "events-test.jsonl"
        with p.open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        return p

class TestPipelineThreshold(PipelineBase):
    def test_score_below_proposal_threshold_dropped(self):
        self._seed_events([
            {"evt_type": "context.warn.red", "payload": {"pct": 92,
             "error": "bad"}},
        ])
        with patch("_ollama.score_hint", return_value={
                "gold_worthy": False, "confidence": 0.40,
                "pattern": "x", "tag": "y", "reason": "weak",
        }):
            summary = gold_mine.run_mine()
        self.assertEqual(summary["dropped"], 1)
        self.assertFalse(gold_mine.proposals_path().is_file())

    def test_score_in_proposal_band_writes_proposal(self):
        self._seed_events([
            {"evt_type": "context.warn.red", "payload": {"pct": 90}},
        ])
        with patch("_ollama.score_hint", return_value={
                "gold_worthy": True, "confidence": 0.80,
                "pattern": "warn-red recurring", "tag": "ctx",
                "reason": "borderline",
        }):
            summary = gold_mine.run_mine()
        self.assertEqual(summary["proposed"], 1)
        rows = [json.loads(l)
                for l in gold_mine.proposals_path().read_text().splitlines()
                if l]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["score"], 0.80)
        # Required contract fields all present.
        for k in ["id", "ts", "score", "pattern", "tag", "reason",
                   "source_evt", "source_tool", "status"]:
            self.assertIn(k, rows[0])

    def test_score_above_auto_threshold_captures_and_writes(self):
        self._seed_events([
            {"evt_type": "context.warn.red", "payload": {"pct": 95}},
        ])
        with patch("_ollama.score_hint", return_value={
                "gold_worthy": True, "confidence": 0.92,
                "pattern": "hi-conf gold pattern", "tag": "ctx",
                "reason": "strong",
        }):
            summary = gold_mine.run_mine()
        self.assertEqual(summary["auto-captured"], 1)
        # Proposal row marked auto-captured.
        rows = [json.loads(l)
                for l in gold_mine.proposals_path().read_text().splitlines()
                if l]
        self.assertEqual(rows[0]["status"], "auto-captured")
        # patterns.jsonl now has a capture.
        patterns = Path(os.environ["KAIZEN_GOLD_FILE"])
        self.assertTrue(patterns.is_file())
        cap = json.loads(patterns.read_text().strip())
        self.assertEqual(cap["tag"], "auto-mined")

    def test_unscored_when_ollama_returns_none(self):
        self._seed_events([
            {"evt_type": "auto_handoff.requested", "payload": {}},
        ])
        with patch("_ollama.score_hint", return_value=None):
            summary = gold_mine.run_mine()
        self.assertEqual(summary["unscored"], 1)
        self.assertFalse(gold_mine.proposals_path().is_file())

    def test_disable_knob_no_pipeline_run(self):
        self._seed_events([
            {"evt_type": "context.warn.red", "payload": {"pct": 92}},
        ])
        os.environ["KAIZEN_GOLD_DISABLE"] = "1"
        try:
            with patch("_ollama.score_hint", return_value={
                    "gold_worthy": True, "confidence": 0.92,
                    "pattern": "x", "tag": "y", "reason": "z"}) as mock:
                summary = gold_mine.run_mine()
            self.assertEqual(summary.get("filtered", 0), 0)
            mock.assert_not_called()
        finally:
            os.environ.pop("KAIZEN_GOLD_DISABLE", None)

class TestPipelineFiltering(PipelineBase):
    def test_anti_recursion_kaizen_gold_events_skipped(self):
        self._seed_events([
            {"evt_type": "gold.captured", "tool_name": "kaizen-gold",
             "payload": {"id": 1}},
            {"evt_type": "auto_handoff.requested", "payload": {}},
        ])
        with patch("_ollama.score_hint", return_value={
                "gold_worthy": False, "confidence": 0.40,
                "pattern": "x", "tag": "y", "reason": "z"}):
            summary = gold_mine.run_mine()
        # Only 1 event survives filter — the auto_handoff one.
        self.assertEqual(summary["filtered"], 1)

    def test_cursor_advanced_after_run(self):
        self._seed_events([{"evt_type": "Stop"}])
        with patch("_ollama.score_hint", return_value=None):
            gold_mine.run_mine()
        cur = gold_mine.load_cursor()
        self.assertIn("dxm", cur)
        # Per-file cursor under dxm.
        self.assertTrue(any("events-" in k for k in cur["dxm"]))

if __name__ == "__main__":
    unittest.main()
