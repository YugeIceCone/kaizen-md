"""Tests for daemon.py — the kaizen plugin-source watch daemon."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import daemon  # noqa: E402


class TestScriptsDir(unittest.TestCase):
    def test_scripts_dir_exists_and_holds_daemon(self):
        d = daemon.scripts_dir()
        self.assertTrue(d.is_dir(), f"{d} should exist")
        self.assertTrue((d / "daemon.py").is_file(),
                        f"{d} should contain daemon.py")
        self.assertTrue((d / "hygiene.py").is_file())
        self.assertTrue((d / "refresh-cache.sh").is_file())


class TestIndexRefresh(unittest.TestCase):
    def test_tick_index_step_calls_indexers(self):
        with mock.patch.object(daemon, "run_refresh_cache",
                               return_value=(True, "")), \
             mock.patch.object(daemon, "run_hygiene_fix",
                               return_value=(True, "")), \
             mock.patch.object(daemon, "remote_sha", return_value=""), \
             mock.patch.object(daemon, "local_sha", return_value=""), \
             mock.patch.object(daemon, "_run_index_refresh",
                               return_value=(True, "")) as ri:
            os.environ.pop("KAIZEN_DAEMON_INDEX_DISABLE", None)
            daemon.tick()
            ri.assert_called_once()

    def test_index_disable_knob_skips_refresh(self):
        with mock.patch.object(daemon, "run_refresh_cache",
                               return_value=(True, "")), \
             mock.patch.object(daemon, "run_hygiene_fix",
                               return_value=(True, "")), \
             mock.patch.object(daemon, "remote_sha", return_value=""), \
             mock.patch.object(daemon, "local_sha", return_value=""), \
             mock.patch.object(daemon, "_run_index_refresh") as ri:
            os.environ["KAIZEN_DAEMON_INDEX_DISABLE"] = "1"
            try:
                daemon.tick()
                ri.assert_not_called()
            finally:
                os.environ.pop("KAIZEN_DAEMON_INDEX_DISABLE", None)


class TestIndexStatus(unittest.TestCase):
    def test_index_status_reports_stale_when_source_newer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".kaizen").mkdir()
            # no loc.db at all → stale ("never indexed")
            st = daemon.index_status(root)
            self.assertFalse(st["fresh"])
            self.assertIn("never", st["reason"].lower())


class TestWatchBackendSelect(unittest.TestCase):
    def test_watchdog_available_true_when_importable(self):
        with mock.patch.dict("sys.modules", {"watchdog": mock.MagicMock()}):
            self.assertTrue(daemon._watchdog_available())

    def test_watchdog_available_false_when_missing(self):
        real_import = __import__

        def fake_import(name, *a, **k):
            if name == "watchdog" or name.startswith("watchdog."):
                raise ImportError("no watchdog")
            return real_import(name, *a, **k)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            self.assertFalse(daemon._watchdog_available())

    def test_ignore_patterns_cover_kaizen_and_git(self):
        # The self-trigger guard: .kaizen/ must be ignored.
        joined = " ".join(daemon._WATCH_IGNORE)
        self.assertIn(".kaizen", joined)
        self.assertIn(".git", joined)
        self.assertIn("__pycache__", joined)


if __name__ == "__main__":
    unittest.main()
