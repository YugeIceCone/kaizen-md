"""Tests for hooks/claude/cwdchanged-memory-sync.sh.

CwdChanged hook: when Claude crosses into a new git repo, fire
kaizen-auto-load + kaizen-better-memory regen for the NEW cwd so
subsequent reads don't see stale per-project state.

Non-blocking by contract.
Sandbox: KAIZEN_CWDCHANGED_SYNC_DISABLE skips the work.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HOOK = ROOT / "hooks/claude/cwdchanged-memory-sync.sh"


class TestCwdChangedHook(unittest.TestCase):

    def test_present_and_executable(self):
        self.assertTrue(_HOOK.is_file(), f"missing: {_HOOK}")
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_exits_zero_on_empty_stdin(self):
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input="", capture_output=True, text=True, timeout=5,
            env={**os.environ,
                 "KAIZEN_TRACE_DISABLE": "1",
                 "KAIZEN_CWDCHANGED_SYNC_DISABLE": "1"},
        )
        self.assertEqual(r.returncode, 0,
            "CwdChanged hook MUST never block — always exit 0")

    def test_exits_zero_on_valid_event(self):
        payload = {
            "session_id": "s1",
            "hook_event_name": "CwdChanged",
            "old_cwd": "/home/u/projA",
            "new_cwd": "/home/u/projB",
        }
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=5,
            env={**os.environ,
                 "KAIZEN_TRACE_DISABLE": "1",
                 "KAIZEN_CWDCHANGED_SYNC_DISABLE": "1"},
        )
        self.assertEqual(r.returncode, 0)

    def test_exits_zero_on_malformed_json(self):
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input="not json at all",
            capture_output=True, text=True, timeout=5,
            env={**os.environ,
                 "KAIZEN_TRACE_DISABLE": "1",
                 "KAIZEN_CWDCHANGED_SYNC_DISABLE": "1"},
        )
        self.assertEqual(r.returncode, 0)

    def test_returns_quickly_even_when_enabled(self):
        """Daemon work is backgrounded; the hook itself must return fast."""
        import time
        payload = {"session_id": "x", "hook_event_name": "CwdChanged",
                    "new_cwd": "/tmp"}
        t0 = time.monotonic()
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "KAIZEN_TRACE_DISABLE": "1"},
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(r.returncode, 0)
        self.assertLess(elapsed, 2.0,
            f"hook took {elapsed:.2f}s — should background the work")


if __name__ == "__main__":
    unittest.main()
