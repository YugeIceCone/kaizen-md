"""Tests for _daemon_jobs.py — pure-function daemon job registry.

Each run_<job>(state) returns (ok: bool, msg: str, action_key: str).
Jobs honor KAIZEN_DAEMON_<JOB>_DISABLE env knob (drift-resilient read).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "workflow" / "scripts"))


def _fake_proc(rc: int = 0, stdout: str = "{}", stderr: str = ""):
    class R:
        returncode = rc
    R.stdout = stdout
    R.stderr = stderr
    return R


class TestRunBrainAudit(unittest.TestCase):

    def test_disabled_via_env_returns_skipped(self):
        import _daemon_jobs as jobs
        with patch.dict(os.environ, {"KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE": "1"}):
            ok, msg, action = jobs.run_brain_audit(state={})
        self.assertTrue(ok)
        self.assertEqual(action, "brain-audit")
        self.assertIn("disabled", msg.lower())

    def test_enabled_invokes_brain_audit_apply(self):
        import _daemon_jobs as jobs
        called = {}

        def fake_run(cmd, **kw):
            called["cmd"] = list(cmd)
            return _fake_proc()

        env_copy = {k: v for k, v in os.environ.items()
                    if k != "KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE"}
        with patch.dict(os.environ, env_copy, clear=True), \
             patch("subprocess.run", side_effect=fake_run):
            ok, msg, action = jobs.run_brain_audit(state={})

        self.assertTrue(ok)
        self.assertEqual(action, "brain-audit")
        self.assertIn("brain_audit", " ".join(called["cmd"]))
        self.assertIn("--apply", called["cmd"])

    def test_nonzero_rc_returns_not_ok(self):
        import _daemon_jobs as jobs

        def fake_run(cmd, **kw):
            return _fake_proc(rc=2, stderr="boom")

        env_copy = {k: v for k, v in os.environ.items()
                    if k != "KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE"}
        with patch.dict(os.environ, env_copy, clear=True), \
             patch("subprocess.run", side_effect=fake_run):
            ok, msg, _ = jobs.run_brain_audit(state={})

        self.assertFalse(ok)
        self.assertIn("rc=2", msg)


if __name__ == "__main__":
    unittest.main()
