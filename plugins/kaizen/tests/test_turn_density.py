"""turn-density (idea #101): count events per UserPromptSubmit turn."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import turn_density  # noqa: E402


class TestTurnDensity(unittest.TestCase):
    def test_density_per_turn(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "trace.jsonl"
            log.write_text(
                json.dumps({"event": "UserPromptSubmit", "ts": "T1", "turn": 1}) + "\n"
                + json.dumps({"event": "ToolUse", "ts": "T2", "turn": 1}) + "\n"
                + json.dumps({"event": "ToolUse", "ts": "T3", "turn": 1}) + "\n"
                + json.dumps({"event": "UserPromptSubmit", "ts": "T4", "turn": 2}) + "\n"
                + json.dumps({"event": "ToolUse", "ts": "T5", "turn": 2}) + "\n"
            )
            rep = turn_density.scan(trace_log=log)
            self.assertEqual(rep["turns"][1]["events"], 3)
            self.assertEqual(rep["turns"][2]["events"], 2)

    def test_missing_log(self):
        rep = turn_density.scan(trace_log=Path("/nonexistent.jsonl"))
        self.assertEqual(rep["turns"], {})


if __name__ == "__main__":
    unittest.main()
