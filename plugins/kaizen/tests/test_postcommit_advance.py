"""TDD for Phase 8 — post-commit git hook auto-advances workflow state.

Tests invoke the hook script directly (not via real git) with a
planted state.json + schema, then assert the state file was advanced.

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_postcommit_advance -v
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
HOOK = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "post-commit.sh"


_SCHEMA = """\
name: pc-schema
version: 1
description: post-commit fixture.

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


def _plant(root: Path, state: dict | None = None) -> None:
    sd = root / ".kaizen" / "workflow" / "schemas" / "pc-schema"
    sd.mkdir(parents=True)
    (sd / "schema.yaml").write_text(_SCHEMA)
    (root / ".git").mkdir(exist_ok=True)
    if state is not None:
        (root / ".kaizen" / "workflow" / "state.json").write_text(json.dumps(state))


def _run(project_root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "KAIZEN_PROJECT_ROOT_OVERRIDE": str(project_root)}
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True, text=True, env=env, timeout=10,
        cwd=str(project_root),
    )


class TestPostCommitAdvance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_file = self.root / ".kaizen" / "workflow" / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_advances_when_active_workflow(self):
        _plant(self.root, state={
            "schema": "pc-schema", "current_stage": "alpha",
            "completed": [], "remaining": ["beta"], "done": False,
        })
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["current_stage"], "beta")
        self.assertIn("alpha", state["completed"])

    def test_noop_when_no_state(self):
        _plant(self.root, state=None)
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.state_file.exists())

    def test_noop_when_already_done(self):
        _plant(self.root, state={
            "schema": "pc-schema", "current_stage": None,
            "completed": ["alpha", "beta"], "remaining": [], "done": True,
        })
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        # State is unchanged
        self.assertTrue(state["done"])
        self.assertEqual(state["completed"], ["alpha", "beta"])

    def test_disable_env_skips(self):
        _plant(self.root, state={
            "schema": "pc-schema", "current_stage": "alpha",
            "completed": [], "remaining": ["beta"], "done": False,
        })
        env = {**os.environ,
               "KAIZEN_PROJECT_ROOT_OVERRIDE": str(self.root),
               "KAIZEN_POSTCOMMIT_ADVANCE_DISABLE": "1"}
        r = subprocess.run(
            ["bash", str(HOOK)],
            capture_output=True, text=True, env=env, timeout=10,
            cwd=str(self.root),
        )
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["current_stage"], "alpha")  # unchanged


if __name__ == "__main__":
    unittest.main()
