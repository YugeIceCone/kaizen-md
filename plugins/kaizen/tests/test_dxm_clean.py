"""Tests for `kaizen-dxm clean` — retention / rotation (BK-009).

Without cleanup, events-<sid>.jsonl files accumulate forever.
Removes stale per-session files by age (mtime) or by --all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_DXM_PY = _KZ_DIR / "scripts" / "observe" / "dxm.py"


class CleanBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_DXM_DIR")
        os.environ["KAIZEN_DXM_DIR"] = str(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_DXM_DIR", None)
        else: os.environ["KAIZEN_DXM_DIR"] = self._orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DXM_PY), *args],
            capture_output=True, text=True, timeout=15, env=os.environ.copy(),
        )

    def _seed(self, name: str, age_seconds: float):
        """Create an events file backdated by age_seconds."""
        p = self.tmp / name
        p.write_text("{}\n")
        mt = time.time() - age_seconds
        os.utime(p, (mt, mt))


class TestCleanByAge(CleanBase):
    def test_older_than_removes_stale_files(self):
        self._seed("events-old.jsonl", age_seconds=7 * 86400 + 60)   # >7d
        self._seed("events-fresh.jsonl", age_seconds=60)             # <1m
        r = self._run("clean", "--older-than", "7d", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["removed_count"], 1)
        self.assertFalse((self.tmp / "events-old.jsonl").exists())
        self.assertTrue((self.tmp / "events-fresh.jsonl").exists())

    def test_older_than_accepts_h_units(self):
        self._seed("events-2h.jsonl", age_seconds=2 * 3600 + 10)
        self._seed("events-30m.jsonl", age_seconds=30 * 60)
        r = self._run("clean", "--older-than", "1h", "--json")
        env = json.loads(r.stdout)
        # 2h-old removed; 30m-old kept
        self.assertEqual(env["data"]["removed_count"], 1)
        self.assertFalse((self.tmp / "events-2h.jsonl").exists())
        self.assertTrue((self.tmp / "events-30m.jsonl").exists())

    def test_older_than_accepts_m_units(self):
        self._seed("events-old-m.jsonl", age_seconds=120)
        self._seed("events-fresh-m.jsonl", age_seconds=10)
        r = self._run("clean", "--older-than", "1m", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["removed_count"], 1)

    def test_older_than_seconds(self):
        self._seed("events-stale.jsonl", age_seconds=10)
        self._seed("events-now.jsonl", age_seconds=0.1)
        r = self._run("clean", "--older-than", "5s", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["removed_count"], 1)


class TestCleanAll(CleanBase):
    def test_all_removes_everything_under_dxm_dir(self):
        self._seed("events-a.jsonl", age_seconds=0)
        self._seed("events-b.jsonl", age_seconds=0)
        self._seed("sessions.jsonl", age_seconds=0)
        r = self._run("clean", "--all", "--json")
        env = json.loads(r.stdout)
        self.assertGreaterEqual(env["data"]["removed_count"], 3)
        self.assertFalse((self.tmp / "events-a.jsonl").exists())
        self.assertFalse((self.tmp / "events-b.jsonl").exists())


class TestCleanDryRun(CleanBase):
    def test_dry_run_reports_but_does_not_remove(self):
        self._seed("events-old.jsonl", age_seconds=8 * 86400)
        r = self._run("clean", "--older-than", "7d", "--dry-run", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["would_remove_count"], 1)
        # File still exists
        self.assertTrue((self.tmp / "events-old.jsonl").exists())


class TestCleanInvalidAge(CleanBase):
    def test_garbage_age_string_rejected(self):
        r = self._run("clean", "--older-than", "garbage", "--json")
        self.assertNotEqual(r.returncode, 0)


class TestCleanEmptyDir(CleanBase):
    def test_no_files_to_remove(self):
        r = self._run("clean", "--older-than", "1d", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["removed_count"], 0)


class TestCleanHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run([sys.executable, str(_DXM_PY), "clean", "--help"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
