"""hook-cascade (idea #62): detect hooks that fire together (co-occurrence)."""
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

import hook_cascade  # noqa: E402

class TestHookCascade(unittest.TestCase):
    def test_co_occurrence(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "trace.jsonl"
            log.write_text("".join(json.dumps(ev) + "\n" for ev in [
                {"event": "hook_fired", "hook": "a.sh", "ts_epoch": 100},
                {"event": "hook_fired", "hook": "b.sh", "ts_epoch": 100},
                {"event": "hook_fired", "hook": "a.sh", "ts_epoch": 200},
                {"event": "hook_fired", "hook": "b.sh", "ts_epoch": 200},
                {"event": "hook_fired", "hook": "a.sh", "ts_epoch": 300},
                {"event": "hook_fired", "hook": "b.sh", "ts_epoch": 300},
                {"event": "hook_fired", "hook": "c.sh", "ts_epoch": 400},
            ]))
            rep = hook_cascade.scan(trace_log=log, window_seconds=1)
            pairs = {(p["a"], p["b"]): p["count"] for p in rep["cascades"]}
            ab = pairs.get(("a.sh", "b.sh")) or pairs.get(("b.sh", "a.sh"))
            self.assertEqual(ab, 3)

    def test_missing_log(self):
        rep = hook_cascade.scan(trace_log=Path("/nonexistent.jsonl"))
        self.assertEqual(rep["cascades"], [])

if __name__ == "__main__":
    unittest.main()
