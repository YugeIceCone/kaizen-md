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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "daemon"))
import daemon  # noqa: E402


class TestScriptsDir(unittest.TestCase):
    def test_scripts_dir_exists_and_holds_daemon(self):
        # Post-DOMAIN-6 + v1.40 consolidation: scripts_dir() returns
        # the legacy skills/workflow/scripts/ for the .py shim cluster
        # (e.g. hygiene.py — still a shim there). refresh-cache.sh
        # canonical moved to scripts/install/ during the .sh shim
        # sweep; daemon.run_refresh_cache uses the canonical path
        # directly now.
        d = daemon.scripts_dir()
        self.assertTrue(d.is_dir(), f"{d} should exist")
        self.assertTrue((d / "hygiene.py").is_file())
        plugin_root = daemon.plugin_src()
        self.assertTrue(
            (plugin_root / "scripts" / "install" / "refresh-cache.sh").is_file()
        )
        # daemon.py is now under scripts/daemon/ (post-DOMAIN-6).
        plugin_root = daemon.plugin_src()
        self.assertTrue((plugin_root / "scripts" / "daemon" / "daemon.py").is_file(),
                        "daemon.py should live at scripts/daemon/ after DOMAIN-6")


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


class TestDaemonUvScript(unittest.TestCase):
    def test_daemon_is_a_uv_run_script(self):
        lines = (Path(__file__).resolve().parent.parent / "scripts" / "daemon" / "daemon.py").read_text().splitlines()
        self.assertIn("uv run --script", lines[0],
                      "daemon.py shebang must invoke uv run --script")

    def test_daemon_declares_watchdog_dependency(self):
        text = (Path(__file__).resolve().parent.parent / "scripts" / "daemon" / "daemon.py").read_text()
        self.assertRegex(text, r"#\s*dependencies\s*=.*watchdog",
                         "watchdog must be declared in the # /// script block")

    def test_uv_constant_resolved(self):
        # daemon.UV is the resolved uv binary (abs path when found, bare
        # 'uv' otherwise) — used for cron lines + the watch-start Popen.
        self.assertTrue(daemon.UV)
        self.assertIn("uv", daemon.UV)


class TestCronSupervisor(unittest.TestCase):
    def test_cron_install_supervises_watch_start(self):
        captured = {}

        def fake_run(argv, **kw):
            if argv[:2] == ["crontab", "-l"]:
                return mock.Mock(returncode=1, stdout="")
            if argv[:2] == ["crontab", "-"]:
                captured["crontab"] = kw.get("input", "")
                return mock.Mock(returncode=0, stderr="")
            return mock.Mock(returncode=0, stdout="")

        with mock.patch.object(daemon.subprocess, "run", side_effect=fake_run):
            ok = daemon.cron_install(interval_min=30)
        self.assertTrue(ok)
        cron = captured["crontab"]
        self.assertIn("watch-start", cron)
        self.assertIn("@reboot", cron)
        self.assertNotRegex(cron, r"daemon\.py run\b")


if __name__ == "__main__":
    unittest.main()
