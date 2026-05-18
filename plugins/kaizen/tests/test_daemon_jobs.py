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


class TestRunBrainIndex(unittest.TestCase):

    def test_disabled_via_env_returns_skipped(self):
        import _daemon_jobs as jobs
        with patch.dict(os.environ, {"KAIZEN_DAEMON_BRAIN_INDEX_DISABLE": "1"}):
            ok, msg, action = jobs.run_brain_index(state={})
        self.assertTrue(ok)
        self.assertEqual(action, "brain-index")
        self.assertIn("disabled", msg.lower())

    def test_no_drift_skips_reindex(self):
        import _daemon_jobs as jobs
        state = {"brain_notes_hash": "abc123"}
        env_copy = {k: v for k, v in os.environ.items()
                    if k != "KAIZEN_DAEMON_BRAIN_INDEX_DISABLE"}
        with patch.dict(os.environ, env_copy, clear=True), \
             patch.object(jobs, "_brain_notes_hash", return_value="abc123"), \
             patch("subprocess.run") as run:
            ok, msg, action = jobs.run_brain_index(state)
        run.assert_not_called()
        self.assertTrue(ok)
        self.assertEqual(action, "brain-index")
        self.assertIn("no drift", msg.lower())
        self.assertEqual(state["brain_notes_hash"], "abc123")

    def test_drift_triggers_reindex_and_updates_hash(self):
        import _daemon_jobs as jobs
        state = {"brain_notes_hash": "OLD"}

        def fake_run(cmd, **kw):
            return _fake_proc()

        env_copy = {k: v for k, v in os.environ.items()
                    if k != "KAIZEN_DAEMON_BRAIN_INDEX_DISABLE"}
        with patch.dict(os.environ, env_copy, clear=True), \
             patch.object(jobs, "_brain_notes_hash", return_value="NEW"), \
             patch("subprocess.run", side_effect=fake_run) as run:
            ok, msg, _ = jobs.run_brain_index(state)

        self.assertTrue(ok)
        self.assertEqual(state["brain_notes_hash"], "NEW")
        # Confirm we shelled out to brain_index.py index
        called = list(run.call_args[0][0])
        self.assertIn("brain_index.py", " ".join(called))
        self.assertIn("index", called)

    def test_failed_reindex_keeps_old_hash(self):
        import _daemon_jobs as jobs
        state = {"brain_notes_hash": "OLD"}

        def fake_run(cmd, **kw):
            return _fake_proc(rc=1, stderr="db locked")

        env_copy = {k: v for k, v in os.environ.items()
                    if k != "KAIZEN_DAEMON_BRAIN_INDEX_DISABLE"}
        with patch.dict(os.environ, env_copy, clear=True), \
             patch.object(jobs, "_brain_notes_hash", return_value="NEW"), \
             patch("subprocess.run", side_effect=fake_run):
            ok, _, _ = jobs.run_brain_index(state)

        self.assertFalse(ok)
        # On failure, hash must NOT advance — next tick retries.
        self.assertEqual(state["brain_notes_hash"], "OLD")


if __name__ == "__main__":
    unittest.main()
