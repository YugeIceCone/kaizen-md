"""TDD-RED for `kaizen-workflow-config run` subcommand (Phase 4).

Thin wrapper that:
  1. Reads schema_name from persisted config (project ← global merge)
     unless --schema overrides.
  2. Invokes workflow_runner.cmd_start(schema, force=...)
  3. Optionally prints current stage on success.

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_workflow_config_run -v
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
SCRIPT = PLUGIN_ROOT / "scripts" / "workflow" / "workflow_config.py"


_SCHEMA = """\
name: r-schema
version: 1
description: Run-subcommand fixture.

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


def _plant(root: Path, persisted_schema: str | None = None) -> Path:
    sd = root / ".kaizen" / "workflow" / "schemas" / "r-schema"
    sd.mkdir(parents=True)
    (sd / "schema.yaml").write_text(_SCHEMA)
    (root / ".git").mkdir(exist_ok=True)
    cfg_path = root / ".kaizen" / "workflow.json"
    if persisted_schema:
        cfg_path.write_text(json.dumps({
            "version": 1,
            "schema_name": persisted_schema,
            "run_mode": "schema",
        }))
    return cfg_path


def _run(*args: str, project_root: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if project_root is not None:
        env["KAIZEN_PROJECT_ROOT_OVERRIDE"] = str(project_root)
        env["KAIZEN_WORKFLOW_CONFIG_PATH"] = str(project_root / ".kaizen" / "workflow.json")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "run", *args],
        capture_output=True, text=True, env=env, timeout=10,
        cwd=str(project_root) if project_root else None,
    )


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_file = self.root / ".kaizen" / "workflow" / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_with_explicit_schema_starts_state(self):
        _plant(self.root)
        r = _run("--schema", "r-schema", project_root=self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(self.state_file.exists())
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["schema"], "r-schema")
        self.assertEqual(state["current_stage"], "alpha")

    def test_run_falls_back_to_persisted_schema_name(self):
        _plant(self.root, persisted_schema="r-schema")
        r = _run(project_root=self.root)  # no --schema arg
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["schema"], "r-schema")

    def test_run_errors_when_no_schema_anywhere(self):
        _plant(self.root)  # no persisted config
        r = _run(project_root=self.root)
        self.assertNotEqual(0, r.returncode)
        self.assertIn("schema", r.stderr.lower())

    def test_run_force_overrides_existing_state(self):
        _plant(self.root)
        _run("--schema", "r-schema", project_root=self.root)
        # Re-run without --force: should fail (state exists)
        r = _run("--schema", "r-schema", project_root=self.root)
        self.assertNotEqual(0, r.returncode)
        # Re-run with --force: succeeds
        r2 = _run("--schema", "r-schema", "--force", project_root=self.root)
        self.assertEqual(0, r2.returncode, r2.stderr)


if __name__ == "__main__":
    unittest.main()
