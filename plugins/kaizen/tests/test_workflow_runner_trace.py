"""TDD-RED for Phase 5 — workflow_runner emits schema.* trace events.

State-machine transitions emit structured events to the kaizen trace:
  schema.start    — cmd_start success
  schema.advance  — cmd_advance moves to next stage
  schema.done     — cmd_advance completes the final stage
  schema.reset    — cmd_state_reset --yes deletes state

KAIZEN_TRACE_DIR env override is used to isolate test events to a tmpdir.

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_workflow_runner_trace -v
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
SCRIPT = PLUGIN_ROOT / "scripts" / "workflow" / "workflow_runner.py"


_SCHEMA = """\
name: tr-schema
version: 1
description: trace fixture.

artifacts:
  - id: alpha
    generates: a/<x>.md
    template: null
    requires: []
    description: first
    gate: alpha gate

  - id: beta
    generates: b/<x>.md
    template: null
    requires: [alpha]
    description: second
    gate: beta gate

apply:
  gate: beta
  progress: .kaizen/workflow/progress.md
  description: gated on beta
"""


def _plant(root: Path) -> None:
    sd = root / ".kaizen" / "workflow" / "schemas" / "tr-schema"
    sd.mkdir(parents=True)
    (sd / "schema.yaml").write_text(_SCHEMA)
    (root / ".git").mkdir(exist_ok=True)


def _run(*args: str, project_root: Path, trace_dir: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "KAIZEN_PROJECT_ROOT_OVERRIDE": str(project_root),
        "KAIZEN_TRACE_DIR":             str(trace_dir),
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env, timeout=10,
        cwd=str(project_root),
    )


def _events(trace_dir: Path) -> list[dict]:
    f = trace_dir / "events.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def _evts_with(events: list[dict], name: str) -> list[dict]:
    return [e for e in events if e.get("evt") == name]


class TestTraceEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.trace_dir = Path(self.tmp.name) / "trace"
        self.root.mkdir()
        self.trace_dir.mkdir()
        _plant(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_emits_schema_start(self):
        r = _run("start", "tr-schema", project_root=self.root, trace_dir=self.trace_dir)
        self.assertEqual(0, r.returncode, r.stderr)
        starts = _evts_with(_events(self.trace_dir), "schema.start")
        self.assertEqual(1, len(starts))
        self.assertEqual(starts[0]["data"]["schema"], "tr-schema")

    def test_advance_emits_schema_advance(self):
        _run("start", "tr-schema", project_root=self.root, trace_dir=self.trace_dir)
        r = _run("advance", project_root=self.root, trace_dir=self.trace_dir)
        self.assertEqual(0, r.returncode, r.stderr)
        advs = _evts_with(_events(self.trace_dir), "schema.advance")
        self.assertEqual(1, len(advs))
        self.assertEqual(advs[0]["data"]["from"], "alpha")
        self.assertEqual(advs[0]["data"]["to"], "beta")

    def test_final_advance_emits_schema_done(self):
        _run("start", "tr-schema", project_root=self.root, trace_dir=self.trace_dir)
        _run("advance", project_root=self.root, trace_dir=self.trace_dir)  # alpha → beta
        _run("advance", project_root=self.root, trace_dir=self.trace_dir)  # beta → done
        done = _evts_with(_events(self.trace_dir), "schema.done")
        self.assertEqual(1, len(done))
        self.assertEqual(done[0]["data"]["schema"], "tr-schema")

    def test_state_reset_emits_schema_reset(self):
        _run("start", "tr-schema", project_root=self.root, trace_dir=self.trace_dir)
        r = _run("state-reset", "--yes", project_root=self.root, trace_dir=self.trace_dir)
        self.assertEqual(0, r.returncode, r.stderr)
        resets = _evts_with(_events(self.trace_dir), "schema.reset")
        self.assertEqual(1, len(resets))


if __name__ == "__main__":
    unittest.main()
