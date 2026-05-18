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


def _flush_daemon_modules():
    for m in list(sys.modules):
        if m in ("daemon", "_daemon_jobs"):
            del sys.modules[m]


class TestDaemonBrainAuditWire(unittest.TestCase):

    def test_tick_records_brain_audit_action_when_disabled(self):
        """When KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE=1, the job still
        executes its early-return path and is counted in actions."""
        with tempfile.TemporaryDirectory() as td:
            env = {
                "KAIZEN_DAEMON_STATE": td,
                "KAIZEN_DAEMON_BRAIN_AUDIT_DISABLE": "1",
                "KAIZEN_DAEMON_INDEX_DISABLE": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                _flush_daemon_modules()
                import daemon as d

                # Patch out network + hygiene to keep the tick fast +
                # deterministic — we only care about the brain-audit wire.
                with patch.object(d, "remote_sha", return_value=""), \
                     patch.object(d, "local_sha", return_value=""), \
                     patch.object(d, "run_hygiene_fix",
                                  return_value=(True, "skipped")), \
                     patch.object(d, "dir_hash", return_value=""):
                    state = d.tick()

        self.assertIn("brain-audit", state.get("actions", {}))
        self.assertGreaterEqual(state["actions"]["brain-audit"], 1)


if __name__ == "__main__":
    unittest.main()
