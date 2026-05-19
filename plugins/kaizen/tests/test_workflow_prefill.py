"""TDD-RED for Phase 6 — _workflow_prefill.py helper that produces an
annotation block for the SessionStart intake-hook body when the project
has persisted workflow defaults at .kaizen/workflow.json.

The intake hook concatenates this prefill into its AskUserQuestion
instructional body so the user sees their saved picks as defaults to
confirm-or-override (instead of re-pick from scratch every session).

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_workflow_prefill -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "workflow" / "_workflow_prefill.py"


def _run(workflow_json: dict | None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "workflow.json"
        if workflow_json is not None:
            path.write_text(json.dumps(workflow_json))
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--from", str(path)],
            capture_output=True, text=True, timeout=5,
        )


class TestPrefill(unittest.TestCase):
    def test_empty_path_emits_empty_string(self):
        r = _run(None)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("", r.stdout.strip())

    def test_run_mode_in_prefill(self):
        r = _run({"version": 1, "run_mode": "schema", "schema_name": "semantic-search"})
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("schema", r.stdout)
        self.assertIn("semantic-search", r.stdout)

    def test_disciplines_in_prefill(self):
        r = _run({
            "version": 1,
            "disciplines": ["kiss", "yagni", "tdd", "karpathy"],
        })
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("kiss", r.stdout)
        self.assertIn("karpathy", r.stdout)

    def test_threshold_in_prefill(self):
        r = _run({"version": 1, "auto_handoff_threshold": 75})
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("75", r.stdout)

    def test_full_config_emits_pre_fill_header(self):
        r = _run({
            "version": 1,
            "run_mode": "schema",
            "schema_name": "semantic-search",
            "disciplines": ["kiss", "yagni"],
            "auto_handoff_threshold": 75,
        })
        self.assertEqual(0, r.returncode, r.stderr)
        # Header signals to the agent that these are PRE-FILLED defaults
        self.assertIn("PERSISTED", r.stdout.upper())


if __name__ == "__main__":
    unittest.main()
