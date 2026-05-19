"""End-to-end: daemon.tick() runs brain-audit against a sandbox.

Verifies the new job is wired into the tick orchestrator and counted
in state["actions"]. Sandboxed via KAIZEN_DAEMON_STATE + per-job
DISABLE knobs so the test doesn't shell out to the real audit.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "daemon"))


def _flush_daemon_modules():
    for m in list(sys.modules):
        if m in ("daemon", "_daemon_jobs"):
            del sys.modules[m]


class TestDaemonBrainAuditWire(unittest.TestCase):

    def test_tick_records_brain_jobs_actions(self):
        """A single tick fires every wired brain job and counts it in
        state["actions"]. Sandboxed: each job is force-disabled via env
        so the test stays fast + deterministic — we only verify the
        wiring, not the underlying jobs (those have their own tests)."""
        with tempfile.TemporaryDirectory() as td:
            env = {
                "KAIZEN_DAEMON_STATE": td,
                "KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE": "1",
                "KAIZEN_DAEMON_BRAIN_INDEX_DISABLE": "1",
                "KAIZEN_DAEMON_BRAIN_PROMOTE_DISABLE": "1",
                "KAIZEN_DAEMON_GOLD_MINE_DISABLE": "1",
                "KAIZEN_DAEMON_MEMORY_SYNC_DISABLE": "1",
                "KAIZEN_DAEMON_INDEX_DISABLE": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                _flush_daemon_modules()
                import daemon as d

                # Patch out network + hygiene — we're testing the wire,
                # not the actual jobs.
                with patch.object(d, "remote_sha", return_value=""), \
                     patch.object(d, "local_sha", return_value=""), \
                     patch.object(d, "run_hygiene_fix",
                                  return_value=(True, "skipped")), \
                     patch.object(d, "dir_hash", return_value=""):
                    state = d.tick()

        actions = state.get("actions", {})
        for key in ("brain-audit", "brain-index", "brain-promote",
                    "brain-evolve", "gold-mine", "memory-sync"):
            self.assertIn(key, actions, f"{key} should be wired into tick()")
            self.assertGreaterEqual(actions[key], 1)


if __name__ == "__main__":
    unittest.main()
