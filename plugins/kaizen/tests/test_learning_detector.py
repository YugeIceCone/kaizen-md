"""Tests for learning_detector.py — content-based review trigger.

Sandboxed via KAIZEN_BRAIN_DIR + KAIZEN_GOLD_DIR + tmpdir for ~/.claude/
projects scan. The 3 signal sources are mocked via env knobs / cwd.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_KZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KZ / "scripts/self_improving"))
sys.path.insert(0, str(_KZ / "scripts/io"))

import learning_detector as ld  # noqa: E402


class _DetectorSandbox(unittest.TestCase):
    """Common sandbox: a fake brain Inbox + gold dir + ~/.claude/projects."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.brain = root / "brain"
        (self.brain / "Inbox").mkdir(parents=True)
        self.gold = root / "gold"
        self.gold.mkdir()
        self.projects = root / "claude_projects"
        self.projects.mkdir()
        self._old_env = {
            "KAIZEN_GOLD_DIR": os.environ.get("KAIZEN_GOLD_DIR"),
            "HOME": os.environ.get("HOME"),
        }
        os.environ["KAIZEN_GOLD_DIR"] = str(self.gold)
        os.environ["HOME"] = str(root.parent)  # not used directly here

    def tearDown(self):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()


class TestFindCandidates(_DetectorSandbox):
    def test_no_signals_returns_empty(self):
        out = ld.find_learning_candidates(brain_root=self.brain, since_days=7)
        self.assertEqual(out, [])

    def test_inbox_drafts_picked_up(self):
        (self.brain / "Inbox" / "draft-1.md").write_text("# draft", encoding="utf-8")
        (self.brain / "Inbox" / "draft-2.md").write_text("# draft", encoding="utf-8")
        out = ld.find_learning_candidates(brain_root=self.brain, since_days=7)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(r["signal"] == "inbox" for r in out))

    def test_gold_drops_picked_up(self):
        (self.gold / "discovery-x.md").write_text("# gold", encoding="utf-8")
        out = ld.find_learning_candidates(brain_root=self.brain, since_days=7)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["signal"], "gold")

    def test_since_window_filters_old(self):
        old = self.brain / "Inbox" / "old.md"
        old.write_text("# old", encoding="utf-8")
        # Stamp the file 30 days back
        old_ts = time.time() - (30 * 86400)
        os.utime(old, (old_ts, old_ts))
        # 7-day window excludes it
        out = ld.find_learning_candidates(brain_root=self.brain, since_days=7)
        self.assertEqual(out, [])

    def test_sorted_newest_first(self):
        f1 = self.brain / "Inbox" / "a.md"
        f1.write_text("# a", encoding="utf-8")
        # Stamp f1 older than f2 by manipulating mtime
        os.utime(f1, (time.time() - 3600, time.time() - 3600))
        f2 = self.brain / "Inbox" / "b.md"
        f2.write_text("# b", encoding="utf-8")
        out = ld.find_learning_candidates(brain_root=self.brain, since_days=7)
        self.assertEqual([Path(r["path"]).name for r in out], ["b.md", "a.md"])


class TestShouldTriggerReview(unittest.TestCase):
    def test_below_threshold(self):
        self.assertFalse(ld.should_trigger_review([{"signal": "inbox"}], min_count=3))

    def test_at_threshold(self):
        c = [{"signal": "inbox"}] * 3
        self.assertTrue(ld.should_trigger_review(c, min_count=3))

    def test_above_threshold(self):
        c = [{"signal": "inbox"}] * 5
        self.assertTrue(ld.should_trigger_review(c, min_count=3))


class TestSummarize(unittest.TestCase):
    def test_rollup_by_signal(self):
        c = [
            {"signal": "inbox"}, {"signal": "inbox"},
            {"signal": "gold"},
            {"signal": "project_memory"}, {"signal": "project_memory"},
        ]
        s = ld.summarize(c)
        self.assertEqual(s["total"], 5)
        self.assertEqual(s["by_signal"], {"gold": 1, "inbox": 2, "project_memory": 2})


class TestCli(_DetectorSandbox):
    def test_scan_below_threshold_no_trigger(self):
        rc = ld.main(["scan", "--brain", str(self.brain),
                      "--threshold", "5", "--apply-hook-output"])
        self.assertEqual(rc, 0)
        # No candidates → no hook output emitted, but rc=0.

    def test_scan_above_threshold_emits_hook_output(self):
        for i in range(4):
            (self.brain / "Inbox" / f"d{i}.md").write_text("# x", encoding="utf-8")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ld.main(["scan", "--brain", str(self.brain),
                          "--threshold", "3", "--apply-hook-output"])
        self.assertEqual(rc, 0)
        out = buf.getvalue().strip()
        self.assertTrue(out, "expected hook output emitted")
        payload = json.loads(out)
        self.assertIn("hookSpecificOutput", payload)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertIn("/kaizen:self-improving review",
                      payload["hookSpecificOutput"]["systemMessage"])

    def test_scan_json_envelope_shape(self):
        (self.brain / "Inbox" / "x.md").write_text("# x", encoding="utf-8")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = ld.main(["scan", "--brain", str(self.brain), "--json"])
        self.assertEqual(rc, 0)
        env = json.loads(buf.getvalue())
        self.assertIn("data", env)
        self.assertIn("kaizen", env)
        self.assertEqual(env["kaizen"]["tool"], "kaizen-learning-detector")
        self.assertEqual(env["data"]["summary"]["total"], 1)

    def test_disable_env_knob_short_circuits(self):
        with mock.patch.dict(os.environ, {"KAIZEN_LEARNING_DETECTOR_DISABLE": "1"}):
            rc = ld.main(["scan"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
