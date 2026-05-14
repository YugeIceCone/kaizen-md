"""Tests for daemon.py — the kaizen plugin-source watch daemon."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
