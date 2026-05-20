"""silent-fail (idea #141): detect hooks that fired but returned empty output."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ / "scripts/quality"))

import silent_fail  # noqa: E402

class TestSilentFail(unittest.TestCase):
    def test_detect_empty_output_event(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "trace.jsonl"
            log.write_text(
                json.dumps({"event": "hook_fired", "hook": "foo.sh",
                             "stdout_len": 0, "exit_code": 0}) + "\n"
                + json.dumps({"event": "hook_fired", "hook": "bar.sh",
                              "stdout_len": 42, "exit_code": 0}) + "\n"
                + json.dumps({"event": "hook_fired", "hook": "foo.sh",
                              "stdout_len": 0, "exit_code": 0}) + "\n"
            )
            rep = silent_fail.scan(trace_log=log)
            names = {f["hook"] for f in rep["findings"]}
            self.assertIn("foo.sh", names)
            self.assertNotIn("bar.sh", names)

    def test_empty_log_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "empty.jsonl"
            log.write_text("")
            rep = silent_fail.scan(trace_log=log)
            self.assertEqual(rep["findings"], [])

    def test_missing_log_returns_shape(self):
        rep = silent_fail.scan(trace_log=Path("/nonexistent/x.jsonl"))
        self.assertEqual(rep["findings"], [])
        self.assertIn("note", rep)

if __name__ == "__main__":
    unittest.main()
