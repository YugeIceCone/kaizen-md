"""Tests for hooks/claude/postcompact-refresh-auto-load.sh.

PostCompact hook: after /compact, Claude re-injects CLAUDE.md which
@imports our auto-load.md. The hook fires kaizen-auto-load (async,
backgrounded) so the re-injected content is fresh, not stale.

Non-blocking by contract — must exit 0 instantly.
Sandbox: KAIZEN_POSTCOMPACT_REFRESH_DISABLE skips the work.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HOOK = ROOT / "hooks/claude/postcompact-refresh-auto-load.sh"


class TestHookPresence(unittest.TestCase):

    def test_script_present_and_executable(self):
        self.assertTrue(_HOOK.is_file(), f"missing: {_HOOK}")
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_exits_zero_on_empty_stdin(self):
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input="", capture_output=True, text=True, timeout=5,
            env={**os.environ,
                 "KAIZEN_TRACE_DISABLE": "1",
                 "KAIZEN_POSTCOMPACT_REFRESH_DISABLE": "1"},
        )
        self.assertEqual(r.returncode, 0,
            "PostCompact hook MUST never block — always exits 0")

    def test_exits_zero_on_valid_event(self):
        payload = {
            "session_id": "abc",
            "hook_event_name": "PostCompact",
            "trigger": "manual",
        }
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=5,
            env={**os.environ,
                 "KAIZEN_TRACE_DISABLE": "1",
                 "KAIZEN_POSTCOMPACT_REFRESH_DISABLE": "1"},
        )
        self.assertEqual(r.returncode, 0)

    def test_exits_zero_on_malformed_json(self):
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input="this is not json",
            capture_output=True, text=True, timeout=5,
            env={**os.environ,
                 "KAIZEN_TRACE_DISABLE": "1",
                 "KAIZEN_POSTCOMPACT_REFRESH_DISABLE": "1"},
        )
        # Bad input must not block the session.
        self.assertEqual(r.returncode, 0)


class TestNonBlockingPerformance(unittest.TestCase):
    """The bin is backgrounded — hook must return fast even if the bin
    is slow."""

    def test_hook_returns_quickly_even_when_enabled(self):
        # Enabled (no disable env). The kaizen-auto-load bin runs async
        # so the hook itself should return in well under a second.
        payload = {"session_id": "x", "hook_event_name": "PostCompact"}
        import time
        t0 = time.monotonic()
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "KAIZEN_TRACE_DISABLE": "1"},
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(r.returncode, 0)
        # 2s ceiling — even cold-cache the hook itself shouldn't block.
        self.assertLess(elapsed, 2.0,
            f"hook took {elapsed:.2f}s — should be fast (work backgrounded)")


if __name__ == "__main__":
    unittest.main()
