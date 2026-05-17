"""TDD-RED for workflow_runner state machine (Phase 3 of /kaizen:workflow
full-automation). Adds 5 new verbs:

  start <schema> [--force]   — initialize state.json with first topo stage
  current [--json]            — show current stage's description + gate
  advance                     — mark current done, move to next; final → done
  state [--json]              — print state.json contents
  state-reset [--yes]         — delete state.json (default dry-run)

State.json shape (lives at <repo>/.kaizen/workflow/state.json):

  {
    "schema":        "<name>",
    "schema_path":   "<abs-path>",
    "current_stage": "<artifact-id>" | null (when done),
    "completed":     [<artifact-id>, ...],
    "remaining":     [<artifact-id>, ...],
    "started_at":    "ISO-8601",
    "advanced_at":   "ISO-8601",
    "done":          bool
  }

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_workflow_runner_state -v
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
SCRIPT = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "workflow_runner.py"


_SCHEMA_YAML = """\
name: t-schema
version: 1
description: Fixture for state tests.

artifacts:
  - id: alpha
    generates: a/<x>.md
    template: null
    requires: []
    description: first stage
    gate: alpha gate

  - id: beta
    generates: b/<x>.md
    template: null
    requires: [alpha]
    description: second stage
    gate: beta gate

  - id: gamma
    generates: c/<x>.md
    template: null
    requires: [beta]
    description: third (final) stage
    gate: gamma gate

apply:
  gate: gamma
  progress: .kaizen/workflow/progress.md
  description: gated on gamma
"""


def _plant(project_root: Path) -> None:
    sd = project_root / ".kaizen" / "workflow" / "schemas" / "t-schema"
    sd.mkdir(parents=True)
    (sd / "schema.yaml").write_text(_SCHEMA_YAML)
    # plant .git/ marker so workflow_runner finds project root
    (project_root / ".git").mkdir(exist_ok=True)


def _run(*args: str, project_root: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if project_root is not None:
        env["KAIZEN_PROJECT_ROOT_OVERRIDE"] = str(project_root)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env, timeout=10,
        cwd=str(project_root) if project_root else None,
    )


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _plant(self.project)
        self.state_file = self.project / ".kaizen" / "workflow" / "state.json"

    def tearDown(self):
        self.tmp.cleanup()


# ─── start ────────────────────────────────────────────────────────────


class TestStart(_Base):
    def test_start_creates_state_json(self):
        r = _run("start", "t-schema", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(self.state_file.exists())

    def test_start_state_has_first_topo_stage(self):
        _run("start", "t-schema", project_root=self.project)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["schema"], "t-schema")
        self.assertEqual(state["current_stage"], "alpha")
        self.assertEqual(state["completed"], [])
        self.assertIn("beta", state["remaining"])
        self.assertIn("gamma", state["remaining"])
        self.assertFalse(state["done"])

    def test_start_refuses_to_clobber_existing(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("start", "t-schema", project_root=self.project)
        self.assertNotEqual(0, r.returncode)
        self.assertIn("already", r.stderr.lower() + r.stdout.lower())

    def test_start_force_overwrites(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("start", "t-schema", "--force", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)


# ─── current ──────────────────────────────────────────────────────────


class TestCurrent(_Base):
    def test_current_returns_alpha_after_start(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("current", "--json", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["id"], "alpha")
        self.assertIn("description", payload)
        self.assertIn("gate", payload)

    def test_current_errors_when_no_state(self):
        r = _run("current", project_root=self.project)
        self.assertNotEqual(0, r.returncode)
        self.assertIn("no state", r.stderr.lower() + r.stdout.lower())


# ─── advance ──────────────────────────────────────────────────────────


class TestAdvance(_Base):
    def test_advance_moves_to_next(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("advance", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["current_stage"], "beta")
        self.assertIn("alpha", state["completed"])
        self.assertNotIn("alpha", state["remaining"])

    def test_advance_through_all_stages_marks_done(self):
        _run("start", "t-schema", project_root=self.project)
        _run("advance", project_root=self.project)  # alpha → beta
        _run("advance", project_root=self.project)  # beta → gamma
        _run("advance", project_root=self.project)  # gamma → done
        state = json.loads(self.state_file.read_text())
        self.assertTrue(state["done"])
        self.assertIsNone(state["current_stage"])
        self.assertEqual(state["completed"], ["alpha", "beta", "gamma"])

    def test_advance_errors_when_done(self):
        _run("start", "t-schema", project_root=self.project)
        for _ in range(3):
            _run("advance", project_root=self.project)
        r = _run("advance", project_root=self.project)
        self.assertNotEqual(0, r.returncode)
        self.assertIn("done", r.stderr.lower() + r.stdout.lower())


# ─── state + state-reset ──────────────────────────────────────────────


class TestStateAndReset(_Base):
    def test_state_prints_json(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("state", "--json", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["schema"], "t-schema")

    def test_state_reset_dry_run_keeps_file(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("state-reset", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(self.state_file.exists(),
                        "state-reset without --yes should be dry-run")

    def test_state_reset_yes_deletes_file(self):
        _run("start", "t-schema", project_root=self.project)
        r = _run("state-reset", "--yes", project_root=self.project)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.state_file.exists())


if __name__ == "__main__":
    unittest.main()
