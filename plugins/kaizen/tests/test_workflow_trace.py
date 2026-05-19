"""Workflow stage transitions emit --src workflow trace events."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
WF_SH = PLUGIN / "scripts" / "ops" / "workflow.sh"
TRACE_PY = PLUGIN / "skills" / "workflow" / "scripts" / "trace.py"


class TestWorkflowTraceSource(unittest.TestCase):
    def test_trace_py_accepts_workflow_src(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, KAIZEN_TRACE_DIR=td)
            r = subprocess.run(
                ["python3", str(TRACE_PY), "event", "--src", "workflow",
                 "--evt", "stage-complete", "--tool", "explore"],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.returncode, 0, r.stderr)
            line = (Path(td) / "events.jsonl").read_text().strip()
            self.assertEqual(json.loads(line)["src"], "workflow")


class TestWorkflowShEmitsTrace(unittest.TestCase):
    def test_init_and_advance_emit_workflow_events(self):
        with tempfile.TemporaryDirectory() as td:
            trace_dir = Path(td) / "trace"
            wf_dir = Path(td) / "wf"
            env = dict(os.environ, KAIZEN_TRACE_DIR=str(trace_dir),
                       WORKFLOW_STATE_DIR=str(wf_dir))
            subprocess.run(["bash", str(WF_SH), "init", "build a thing"],
                           env=env, capture_output=True, text=True, timeout=15)
            subprocess.run(["bash", str(WF_SH), "advance", "explore", "done"],
                           env=env, capture_output=True, text=True, timeout=15)
            events = [json.loads(l) for l in
                      (trace_dir / "events.jsonl").read_text().splitlines() if l]
            srcs_evts = {(e["src"], e["evt"]) for e in events}
            self.assertIn(("workflow", "routine-start"), srcs_evts)
            self.assertIn(("workflow", "stage-complete"), srcs_evts)


if __name__ == "__main__":
    unittest.main()
