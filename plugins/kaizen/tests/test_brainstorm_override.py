"""T6 + T6b: override loop preserves auto_bucket, batch env skips ask,
re-score never touches existing manual_bucket."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import brainstorm  # noqa: E402

_SCRIPT = _KZ / "scripts/util/brainstorm.py"
_RUBRIC = _KZ / "schemas/brainstorming/brainstorm-rubric.yaml"

class TestBrainstormOverride(unittest.TestCase):
    def test_manual_bucket_set_preserves_auto(self):
        rows = [{"id": 1, "theme": "x",
                  "idea": "When X then Y something with extra length",
                  "confidence": 0.9, "manual_bucket": "RADICAL"}]
        out = brainstorm.score_jsonl(rows, _RUBRIC)
        self.assertEqual(out[0].get("auto_bucket"), "KEEP")
        self.assertEqual(out[0].get("manual_bucket"), "RADICAL")

    def test_rewrite_preserves_existing_manual_bucket(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "in.jsonl"
            row = {"id": 1, "theme": "x",
                   "idea": "When X then Y something with extra length",
                   "confidence": 0.9, "manual_bucket": "RADICAL"}
            inp.write_text(json.dumps(row) + "\n")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--rewrite"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            new = json.loads(inp.read_text().splitlines()[0])
            self.assertEqual(new["manual_bucket"], "RADICAL")

    def test_empty_jsonl_no_op(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "empty.jsonl"
            inp.write_text("")
            r = subprocess.run(
                [sys.executable, str(_SCRIPT), "score",
                 "--input", str(inp), "--rubric", str(_RUBRIC), "--json"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            self.assertEqual(payload["data"]["rows"], [])

    def test_batch_env_skips_ask(self):
        """KAIZEN_BRAINSTORM_BATCH=1 → run_override_loop is a no-op."""
        rows = [{"id": 1, "theme": "x", "idea": "short",
                 "auto_bucket": "NEEDS_AGENT", "classification_confidence": 0.85,
                 "rationale": "len<8", "rubric_version": "1"}]
        env_was = os.environ.get("KAIZEN_BRAINSTORM_BATCH")
        os.environ["KAIZEN_BRAINSTORM_BATCH"] = "1"
        try:
            out = brainstorm.run_override_loop(rows, ask_user_question=None)
            self.assertEqual(out, rows)  # untouched
        finally:
            if env_was is None:
                del os.environ["KAIZEN_BRAINSTORM_BATCH"]
            else:
                os.environ["KAIZEN_BRAINSTORM_BATCH"] = env_was

    def test_mocked_ask_propagates_manual_bucket(self):
        """T6b: mocked AskUserQuestion returns fixed bucket → row picks it up."""
        rows = [{"id": 7, "theme": "x", "idea": "short",
                 "auto_bucket": "NEEDS_AGENT", "classification_confidence": 0.85,
                 "rationale": "len<8", "rubric_version": "1"}]
        mock_ask = mock.MagicMock(return_value={"7": "RESEARCH"})
        out = brainstorm.run_override_loop(rows, ask_user_question=mock_ask)
        self.assertEqual(out[0].get("manual_bucket"), "RESEARCH")
        self.assertEqual(out[0]["auto_bucket"], "NEEDS_AGENT")

    def test_no_needs_agent_no_call(self):
        """If no rows are NEEDS_AGENT, the ask fn is never called."""
        rows = [{"id": 1, "theme": "x", "idea": "y", "auto_bucket": "KEEP"}]
        mock_ask = mock.MagicMock()
        out = brainstorm.run_override_loop(rows, ask_user_question=mock_ask)
        mock_ask.assert_not_called()
        self.assertEqual(out, rows)

if __name__ == "__main__":
    unittest.main()
