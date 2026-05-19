"""prompt-rhythm (idea #102): time between UserPromptSubmit events."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import prompt_rhythm  # noqa: E402


class TestPromptRhythm(unittest.TestCase):
    def test_intervals_computed(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "trace.jsonl"
            log.write_text("".join(json.dumps(ev) + "\n" for ev in [
                {"event": "UserPromptSubmit", "ts_epoch": 100},
                {"event": "UserPromptSubmit", "ts_epoch": 130},
                {"event": "UserPromptSubmit", "ts_epoch": 200},
            ]))
            rep = prompt_rhythm.scan(trace_log=log)
            self.assertEqual(rep["intervals_seconds"], [30, 70])
            self.assertEqual(rep["mean_seconds"], 50.0)

    def test_missing_log(self):
        rep = prompt_rhythm.scan(trace_log=Path("/nonexistent.jsonl"))
        self.assertEqual(rep["intervals_seconds"], [])


if __name__ == "__main__":
    unittest.main()
