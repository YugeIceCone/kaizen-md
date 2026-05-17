"""TDD — setup-ralph-loop.sh consumes workflow-config loop.max_iterations
when --its / --max-iterations is not provided.

Ralph brainstorm #4 (integration). Explicit --its always wins; otherwise
the workflow-config default is honored; otherwise behaves as today
(MAX_ITERATIONS=0 = unlimited).
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
SETUP_SCRIPT = PLUGIN_ROOT / "skills" / "loop" / "scripts" / "setup-ralph-loop.sh"


class _ConfigSandbox(unittest.TestCase):
    """Each test runs from its own tmp cwd with an isolated workflow-config."""

    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        os.chdir(self.tmp)
        self._orig_env = dict(os.environ)
        # Point both scopes into the tmpdir so the real ~/.claude/ is untouched.
        self.proj_cfg = self.tmp / ".kaizen" / "workflow.json"
        self.glob_cfg = self.tmp / "global" / "workflow-global.json"
        os.environ["KAIZEN_WORKFLOW_CONFIG_PATH"] = str(self.proj_cfg)
        os.environ["KAIZEN_WORKFLOW_GLOBAL_CONFIG_PATH"] = str(self.glob_cfg)

    def tearDown(self):
        os.chdir(self._cwd)
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmp.cleanup()

    def _seed_workflow_config(self, max_iterations: int) -> None:
        """Write a minimal project-scope workflow.json with loop.max_iterations."""
        self.proj_cfg.parent.mkdir(parents=True, exist_ok=True)
        self.proj_cfg.write_text(json.dumps({
            "version": 1,
            "scope": "project",
            "run_mode": "loop",
            "loop": {"max_iterations": max_iterations},
        }))

    def _run_setup(self, *args) -> subprocess.CompletedProcess:
        cmd = ["bash", str(SETUP_SCRIPT), *args]
        return subprocess.run(cmd, cwd=self.tmp, capture_output=True,
                                text=True, env=os.environ.copy(), timeout=20)

    def _state_max_iter(self) -> int:
        """Read .kaizen/loop.state.md and return the max_iterations value."""
        text = (self.tmp / ".kaizen" / "loop.state.md").read_text()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("max_iterations:"):
                return int(line.split(":", 1)[1].strip())
        self.fail(f"max_iterations field missing in state file: {text}")
        return -1


class TestWorkflowConfigDefault(_ConfigSandbox):
    def test_no_its_falls_back_to_workflow_config(self):
        self._seed_workflow_config(42)
        proc = self._run_setup("seed prompt")
        self.assertEqual(proc.returncode, 0,
                          f"stderr={proc.stderr}\nstdout={proc.stdout}")
        self.assertEqual(self._state_max_iter(), 42)
        # The script's stderr surfaces the fallback for observability.
        self.assertIn("workflow-config", proc.stderr)

    def test_explicit_its_overrides_workflow_config(self):
        self._seed_workflow_config(42)
        proc = self._run_setup("--its", "5", "seed prompt")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self._state_max_iter(), 5)
        # No fallback note when --its is explicit.
        self.assertNotIn("defaulted to", proc.stderr.lower())

    def test_no_workflow_config_keeps_unlimited(self):
        """No persisted default + no --its → today's behavior (0=unlimited)."""
        proc = self._run_setup("seed prompt")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self._state_max_iter(), 0)

    def test_zero_value_in_workflow_config_does_not_trigger(self):
        """max_iterations=0 in config is treated as 'not set' (unlimited)."""
        self._seed_workflow_config(0)
        proc = self._run_setup("seed prompt")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self._state_max_iter(), 0)


if __name__ == "__main__":
    unittest.main()
