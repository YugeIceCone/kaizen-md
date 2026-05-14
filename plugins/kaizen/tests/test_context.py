#!/usr/bin/env python3
"""Unit tests for context.py — pure-Python, no subprocess.

Run:
    python3 -m unittest tests.test_context -v
    OR
    python3 tests/test_context.py

Covers:
    - get_tokens: env-var priority, alternate env names, stdin JSON fallback
    - get_limit: default + KAIZEN_CONTEXT_LIMIT override
    - zone_of: green/yellow/red/unknown thresholds
    - missing inputs return None / unknown (no crash)
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))


def _fresh():
    """Reimport context module (no env mutation — caller controls env)."""
    if "context" in sys.modules:
        del sys.modules["context"]
    import context  # noqa: E402
    return context


def _clear_env():
    for k in ("CLAUDE_CONTEXT_TOKENS", "CLAUDE_USAGE_TOTAL_TOKENS", "KAIZEN_CONTEXT_LIMIT"):
        os.environ.pop(k, None)


class TestGetTokens(unittest.TestCase):
    def setUp(self):
        _clear_env()
    def test_env_primary(self):
        os.environ["CLAUDE_CONTEXT_TOKENS"] = "55000"
        c = _fresh()
        self.assertEqual(c.get_tokens(), 55000)

    def test_env_alternate(self):
        os.environ["CLAUDE_USAGE_TOTAL_TOKENS"] = "33000"
        c = _fresh()
        self.assertEqual(c.get_tokens(), 33000)

    def test_env_invalid_falls_through(self):
        os.environ["CLAUDE_CONTEXT_TOKENS"] = "not-a-number"
        c = _fresh()
        # falls through to stdin (empty) → None
        self.assertIsNone(c.get_tokens())

    def test_stdin_total_tokens(self):
        c = _fresh()
        self.assertEqual(c.get_tokens('{"total_tokens": 12345}'), 12345)

    def test_stdin_nested_usage(self):
        c = _fresh()
        self.assertEqual(c.get_tokens('{"usage": {"total_tokens": 9999}}'), 9999)

    def test_stdin_invalid_json(self):
        c = _fresh()
        self.assertIsNone(c.get_tokens("not json"))

    def test_stdin_missing_field(self):
        c = _fresh()
        self.assertIsNone(c.get_tokens('{"other_field": 1}'))

    def test_env_beats_stdin(self):
        os.environ["CLAUDE_CONTEXT_TOKENS"] = "100"
        c = _fresh()
        # env=100 wins over stdin=999
        self.assertEqual(c.get_tokens('{"total_tokens": 999}'), 100)


class TestGetLimit(unittest.TestCase):
    def setUp(self):
        _clear_env()

    def test_default(self):
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)

    def test_override(self):
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "500000"
        c = _fresh()
        self.assertEqual(c.get_limit(), 500_000)

    def test_invalid_falls_back(self):
        os.environ["KAIZEN_CONTEXT_LIMIT"] = "garbage"
        c = _fresh()
        self.assertEqual(c.get_limit(), 200_000)


class TestZone(unittest.TestCase):
    def setUp(self):
        self.c = _fresh()

    def test_green(self):
        self.assertEqual(self.c.zone_of(0), "green")
        self.assertEqual(self.c.zone_of(59), "green")

    def test_yellow(self):
        self.assertEqual(self.c.zone_of(60), "yellow")
        self.assertEqual(self.c.zone_of(79), "yellow")

    def test_red(self):
        self.assertEqual(self.c.zone_of(80), "red")
        self.assertEqual(self.c.zone_of(100), "red")
        self.assertEqual(self.c.zone_of(150), "red")  # over-limit still red

    def test_unknown(self):
        self.assertEqual(self.c.zone_of(None), "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
