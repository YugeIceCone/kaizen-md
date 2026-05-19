"""prompt-event-diff (idea #78): events between two UserPromptSubmit boundaries."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/quality"))

import prompt_event_diff  # noqa: E402


class TestPromptEventDiff(unittest.TestCase):
    def test_slice_between_prompts(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "trace.jsonl"
            log.write_text("".join(json.dumps(ev) + "\n" for ev in [
                {"event": "UserPromptSubmit", "ts_epoch": 100},
                {"event": "ToolUse", "name": "Bash", "ts_epoch": 110},
                {"event": "ToolUse", "name": "Read", "ts_epoch": 120},
                {"event": "UserPromptSubmit", "ts_epoch": 200},
                {"event": "ToolUse", "name": "Edit", "ts_epoch": 210},
                {"event": "UserPromptSubmit", "ts_epoch": 300},
            ]))
            slices = prompt_event_diff.slice_by_prompt(trace_log=log)
            self.assertEqual(len(slices), 3)
            self.assertEqual(slices[0]["event_count"], 2)
            self.assertEqual(slices[1]["event_count"], 1)
            self.assertEqual(slices[2]["event_count"], 0)

    def test_missing_log(self):
        slices = prompt_event_diff.slice_by_prompt(trace_log=Path("/nonexistent.jsonl"))
        self.assertEqual(slices, [])


if __name__ == "__main__":
    unittest.main()
