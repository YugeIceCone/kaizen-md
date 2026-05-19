"""Tests for `auto-finalize --auto-bridge` — close the durables loop.

Per Task #40 brainstorm — item #4 (impact 4 × effort 2 = score 8).
Before this, agents finalized a handoff (auto-finalize) and then had
to remember to separately run `bridge --apply` to capture decisions /
findings / worked / failed into the brain. Now that step folds into
the finalize call.

Gating:
  - Triggered by --auto-bridge flag OR KAIZEN_HANDOFF_AUTO_BRIDGE=1 env
  - Only fires when outcome=SUCCEEDED (high-confidence durables)
  - Other outcomes (PARTIAL_PLUS / PARTIAL_MINUS / FAILED) skip
  - Brain.py subprocess failures don't fail the finalize
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "scripts/handoff/handoff.py"

sys.path.insert(0, str(_KZ / "scripts/handoff"))
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402


_HANDOFF_YAML = """---
session: kaizen-md
date: 2026-05-18
status: partial
outcome: IN_PROGRESS
---

session_meta:
  cc_session_uuid: 'test-sid'
  handoff_generated_at: '2026-05-18T20:00:00Z'

goal: 'demo goal'
now: 'demo next step'
test: pytest

done_this_session: []
blockers: []
questions: []
decisions:
  - 'use the env-overridable-dir pattern for new feature dirs'
  - 'route all paths through _paths.py SSOT constants'
findings:
  - 'PyYAML safe_dump normalizes quoting differently than hand-rolled emitter'
worked:
  - 'TDD RED→GREEN→REFACTOR for net-new code'
failed: []
next: []
files: {}
"""


# ─── _maybe_auto_bridge — gating unit tests ─────────────────────────────

class TestAutoBridgeGating(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.yaml = Path(self._tmp.name) / "h.yaml"
        self.yaml.write_text(_HANDOFF_YAML, encoding="utf-8")
        # Sandbox brain so we don't pollute the real one
        self._orig_brain = os.environ.get("KAIZEN_BRAIN_DIR")
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        os.environ["KAIZEN_BRAIN_DIR"] = str(self.brain)

    def tearDown(self):
        if self._orig_brain is None:
            os.environ.pop("KAIZEN_BRAIN_DIR", None)
        else:
            os.environ["KAIZEN_BRAIN_DIR"] = self._orig_brain
        # Clear the env override knob between tests
        os.environ.pop("KAIZEN_HANDOFF_AUTO_BRIDGE", None)
        self._tmp.cleanup()

    def test_no_flag_no_env_returns_none(self):
        r = _h._maybe_auto_bridge(self.yaml, outcome="SUCCEEDED", force=False)
        self.assertIsNone(r)

    def test_flag_with_succeeded_runs_bridge(self):
        r = _h._maybe_auto_bridge(self.yaml, outcome="SUCCEEDED", force=True)
        self.assertIsNotNone(r)
        self.assertIn("applied", r)
        # We have 4 candidates in the fixture (2 decisions + 1 finding + 1 worked)
        self.assertEqual(r["total"], 4)

    def test_env_with_succeeded_runs_bridge(self):
        os.environ["KAIZEN_HANDOFF_AUTO_BRIDGE"] = "1"
        r = _h._maybe_auto_bridge(self.yaml, outcome="SUCCEEDED", force=False)
        self.assertIsNotNone(r)
        self.assertEqual(r["total"], 4)

    def test_flag_set_but_outcome_not_succeeded_skips(self):
        r = _h._maybe_auto_bridge(self.yaml, outcome="PARTIAL_PLUS", force=True)
        self.assertIsNotNone(r)
        self.assertTrue(r.get("skipped"))
        self.assertIn("PARTIAL_PLUS", r["reason"])

    def test_env_set_but_outcome_failed_skips(self):
        os.environ["KAIZEN_HANDOFF_AUTO_BRIDGE"] = "1"
        r = _h._maybe_auto_bridge(self.yaml, outcome="FAILED", force=False)
        self.assertIsNotNone(r)
        self.assertTrue(r.get("skipped"))


# ─── auto-finalize CLI integration ──────────────────────────────────────

class TestAutoFinalizeAutoBridge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml = self.tmp / "h.yaml"
        self.yaml.write_text(_HANDOFF_YAML, encoding="utf-8")
        # Sandbox brain + handoff DB
        self._orig = {}
        for k, v in (("KAIZEN_BRAIN_DIR", str(self.tmp / "brain")),
                      ("KAIZEN_HANDOFF_DB", str(self.tmp / "handoff.db"))):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v
        (self.tmp / "brain").mkdir()

    def tearDown(self):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.environ.pop("KAIZEN_HANDOFF_AUTO_BRIDGE", None)
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=30,
            env=os.environ.copy(),
        )

    def test_auto_finalize_without_auto_bridge_no_bridge_in_result(self):
        r = self._run("auto-finalize", "--file", str(self.yaml),
                       "--outcome", "SUCCEEDED",
                       "--justification", "test",
                       "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        data = env.get("data", env)
        # No auto_bridge key when not requested
        self.assertNotIn("auto_bridge", data)

    def test_auto_finalize_with_auto_bridge_flag_includes_result(self):
        r = self._run("auto-finalize", "--file", str(self.yaml),
                       "--outcome", "SUCCEEDED",
                       "--justification", "test",
                       "--auto-bridge",
                       "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        data = env.get("data", env)
        self.assertIn("auto_bridge", data)
        ab = data["auto_bridge"]
        # 4 candidates from the fixture
        self.assertEqual(ab["total"], 4)

    def test_auto_finalize_auto_bridge_skips_when_not_succeeded(self):
        r = self._run("auto-finalize", "--file", str(self.yaml),
                       "--outcome", "PARTIAL_PLUS",
                       "--justification", "test",
                       "--auto-bridge",
                       "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        data = env.get("data", env)
        self.assertIn("auto_bridge", data)
        self.assertTrue(data["auto_bridge"].get("skipped"))


if __name__ == "__main__":
    unittest.main()
