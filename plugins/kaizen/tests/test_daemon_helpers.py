"""RED first — tests for the two pure helpers added to daemon.py to
fix the 99%-CPU spin + zombie-child accumulation:

  _should_spawn_semantic(prev_proc, last_spawn, now, throttle_sec)
      → bool. False when a previous refresh is still running OR the
      throttle window hasn't elapsed.

  _resolve_debounce()
      → float. Reads KAIZEN_WATCH_DEBOUNCE_SEC env override; falls
      back to the module default. Clamped to [0.05, 5.0] so a stray
      "0" doesn't burn-loop and a stray "60" doesn't break latency.

Run:
    python3 -m unittest tests.test_daemon_helpers -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "daemon"))

import daemon  # noqa: E402

# ─── _should_spawn_semantic ───────────────────────────────────────────

class ShouldSpawnSemantic(unittest.TestCase):

    def test_spawn_when_no_previous_and_throttle_elapsed(self):
        out = daemon._should_spawn_semantic(
            prev_proc=None, last_spawn=0.0, now=10.0, throttle_sec=5.0,
        )
        self.assertTrue(out)

    def test_no_spawn_when_throttle_window_open(self):
        out = daemon._should_spawn_semantic(
            prev_proc=None, last_spawn=10.0, now=12.0, throttle_sec=5.0,
        )
        self.assertFalse(out)

    def test_no_spawn_when_previous_still_running(self):
        prev = mock.Mock()
        prev.poll.return_value = None   # still running
        out = daemon._should_spawn_semantic(
            prev_proc=prev, last_spawn=0.0, now=100.0, throttle_sec=5.0,
        )
        self.assertFalse(out)
        prev.poll.assert_called_once()

    def test_spawn_when_previous_finished(self):
        prev = mock.Mock()
        prev.poll.return_value = 0   # exited
        out = daemon._should_spawn_semantic(
            prev_proc=prev, last_spawn=0.0, now=100.0, throttle_sec=5.0,
        )
        self.assertTrue(out)

# ─── _resolve_debounce ────────────────────────────────────────────────

class ResolveDebounce(unittest.TestCase):

    def test_default_when_env_unset(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os as _os
            _os.environ.pop("KAIZEN_WATCH_DEBOUNCE_SEC", None)
            out = daemon._resolve_debounce()
            self.assertEqual(out, daemon._WATCH_DEBOUNCE_SEC)

    def test_env_override_honored(self):
        with mock.patch.dict("os.environ", {"KAIZEN_WATCH_DEBOUNCE_SEC": "0.5"}):
            self.assertAlmostEqual(daemon._resolve_debounce(), 0.5)

    def test_env_garbage_falls_back_to_default(self):
        with mock.patch.dict("os.environ", {"KAIZEN_WATCH_DEBOUNCE_SEC": "abc"}):
            self.assertEqual(daemon._resolve_debounce(), daemon._WATCH_DEBOUNCE_SEC)

    def test_env_clamped_to_floor(self):
        """0 would burn-spin → clamp to floor."""
        with mock.patch.dict("os.environ", {"KAIZEN_WATCH_DEBOUNCE_SEC": "0"}):
            self.assertGreaterEqual(daemon._resolve_debounce(), 0.05)

    def test_env_clamped_to_ceiling(self):
        """60s would hurt event latency → clamp to ceiling."""
        with mock.patch.dict("os.environ", {"KAIZEN_WATCH_DEBOUNCE_SEC": "60"}):
            self.assertLessEqual(daemon._resolve_debounce(), 5.0)

# ─── Default debounce shouldn't be the 50ms spinner ───────────────────

class DebounceDefault(unittest.TestCase):

    def test_default_debounce_at_least_quarter_second(self):
        """The original 0.05s default was a 20Hz wake-up loop.
        0.25s or higher = 4Hz, plenty responsive, ~5x less CPU."""
        self.assertGreaterEqual(daemon._WATCH_DEBOUNCE_SEC, 0.25)

if __name__ == "__main__":
    unittest.main()
