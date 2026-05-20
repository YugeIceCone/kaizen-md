#!/usr/bin/env python3
"""Unit tests for inbox.py — uses KAIZEN_INBOX_DIR override.

Covers:
    - capture writes a pending message
    - list filters by drained flag
    - peek shows pending without marking
    - drain marks + returns formatted block
    - clear removes all entries
    - stats counts pending vs drained
    - filename collision-resistance (multiple captures same second)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 — adds scripts/<cluster>/ to sys.path


def _fresh_inbox(tmp: Path):
    os.environ["KAIZEN_INBOX_DIR"] = str(tmp)
    if "inbox" in sys.modules:
        del sys.modules["inbox"]
    import inbox  # noqa: E402
    return inbox


class TestCapture(unittest.TestCase):
    def test_capture_creates_file(self):
        tmp = Path(tempfile.mkdtemp())
        inbox = _fresh_inbox(tmp)
        path = inbox.capture("hello", "sid-1")
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["prompt"], "hello")
        self.assertEqual(data["session_id"], "sid-1")
        self.assertFalse(data["drained"])

    def test_collision_resistant_filenames(self):
        tmp = Path(tempfile.mkdtemp())
        inbox = _fresh_inbox(tmp)
        # Capture rapidly; filenames must differ
        paths = [inbox.capture(f"msg-{i}") for i in range(5)]
        self.assertEqual(len(set(paths)), 5)


class TestList(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = _fresh_inbox(self.tmp)

    def test_empty(self):
        self.assertEqual(self.inbox.list_messages(), [])

    def test_pending_only(self):
        self.inbox.capture("a")
        self.inbox.capture("b")
        msgs = self.inbox.list_messages(pending_only=True)
        self.assertEqual(len(msgs), 2)
        self.assertTrue(all(not m.get("drained") for m in msgs))

    def test_includes_drained_when_all(self):
        self.inbox.capture("a")
        self.inbox.drain()
        # After drain: nothing pending
        self.assertEqual(self.inbox.list_messages(pending_only=True), [])
        # But all=True returns the drained record
        all_msgs = self.inbox.list_messages(pending_only=False)
        self.assertEqual(len(all_msgs), 1)
        self.assertTrue(all_msgs[0]["drained"])


class TestDrain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = _fresh_inbox(self.tmp)

    def test_drain_empty(self):
        self.assertEqual(self.inbox.drain(), "")

    def test_drain_marks_and_returns(self):
        self.inbox.capture("question 1")
        self.inbox.capture("question 2")
        out = self.inbox.drain()
        self.assertIn("USER MESSAGE(S) RECEIVED WHILE BUSY:", out)
        self.assertIn("question 1", out)
        self.assertIn("question 2", out)
        # Second drain is empty (no pending)
        self.assertEqual(self.inbox.drain(), "")

    def test_drain_trailer_discourages_redundant_ack(self):
        """BK-062: the system-reminder containing the drain output
        persists in conversation context after the tool call. The
        trailer must explicitly tell the agent NOT to re-acknowledge
        on subsequent turns if the prior turn already addressed the
        message — otherwise the agent produces noisy duplicate acks."""
        self.inbox.capture("hi mid-busy")
        out = self.inbox.drain()
        # Hard signal — explicit "do NOT re-acknowledge"
        self.assertIn("do NOT re-acknowledge", out)
        # The trailer references the prior-turn check so the rule is
        # actionable, not just a vague suggestion
        self.assertIn("prior assistant turn already addressed", out)

    def test_peek_does_not_mark(self):
        self.inbox.capture("watch me")
        out1 = self.inbox.peek()
        out2 = self.inbox.peek()
        self.assertIn("watch me", out1)
        self.assertIn("watch me", out2)  # still pending


class TestClearAndStats(unittest.TestCase):
    def test_clear_removes_all(self):
        tmp = Path(tempfile.mkdtemp())
        inbox = _fresh_inbox(tmp)
        inbox.capture("a")
        inbox.capture("b")
        inbox.drain()
        inbox.capture("c")  # pending
        n = inbox.clear()
        self.assertEqual(n, 3)
        self.assertEqual(inbox.stats()["total"], 0)

    def test_stats(self):
        tmp = Path(tempfile.mkdtemp())
        inbox = _fresh_inbox(tmp)
        inbox.capture("p1")
        inbox.capture("p2")
        inbox.drain()
        inbox.capture("p3")
        s = inbox.stats()
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["drained"], 2)
        self.assertEqual(s["total"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
