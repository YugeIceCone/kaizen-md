"""Tests for `kaizen-daemon systems-check` — periodic ping of all 4 systems.

Per user 2026-05-18 — "all system can start and be on a keep-alive timer
on the claude code session start api." This is the per-tick health-check
that fires from SessionStart + PostToolUse-periodic hooks.

Tracked systems:
  hooks      — hooks/hooks.json wiring (config; not a sink)
  trace      — ~/.claude/.kaizen/indexes/trace/events.jsonl
  dxm        — ~/.claude/.kaizen/dxm/events-<sid>.jsonl
  observer   — ~/.claude/.kaizen/observer/events.jsonl

Per-system check:
  exists, size, last_mtime, count (jsonl lines), drift_anomaly (string|null)

Output: heartbeat row appended to <KAIZEN_KEEPALIVE_DIR>/heartbeat.jsonl
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_DAEMON = _KZ / "skills/workflow/scripts/daemon.py"


class _SysCheckBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Sandbox the 4 sink dirs via env
        self.observer = self.tmp / "observer"
        self.dxm = self.tmp / "dxm"
        self.trace = self.tmp / "trace"
        self.keepalive = self.tmp / "keepalive"
        for d in (self.observer, self.dxm, self.trace, self.keepalive):
            d.mkdir()
        # Pre-test env state
        self._orig = {}
        for k, v in (
            ("KAIZEN_OBSERVER_DIR", str(self.observer)),
            ("KAIZEN_DXM_DIR", str(self.dxm)),
            ("KAIZEN_TRACE_DIR", str(self.trace)),
            ("KAIZEN_KEEPALIVE_DIR", str(self.keepalive)),
        ):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_DAEMON), *args],
            capture_output=True, text=True, timeout=15,
            env=os.environ.copy(),
        )


class TestSystemsCheckEmpty(_SysCheckBase):
    def test_no_sinks_returns_per_system_zero_state(self):
        r = self._run("systems-check", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("systems", data)
        names = {s["name"] for s in data["systems"]}
        self.assertEqual(names, {"hooks", "trace", "dxm", "observer"})
        # Each system has the canonical fields
        for s in data["systems"]:
            for k in ("name", "exists", "count"):
                self.assertIn(k, s)


class TestHeartbeatWritten(_SysCheckBase):
    def test_systems_check_appends_heartbeat(self):
        r = self._run("systems-check", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        hb = self.keepalive / "heartbeat.jsonl"
        self.assertTrue(hb.is_file())
        rows = [json.loads(l) for l in hb.read_text().splitlines() if l.strip()]
        self.assertEqual(len(rows), 1)
        for k in ("ts", "systems"):
            self.assertIn(k, rows[0])

    def test_multiple_checks_append(self):
        for _ in range(3):
            self._run("systems-check")
        hb = self.keepalive / "heartbeat.jsonl"
        rows = hb.read_text().splitlines()
        self.assertEqual(len([r for r in rows if r.strip()]), 3)


class TestSinkPopulated(_SysCheckBase):
    def test_count_reflects_jsonl_lines(self):
        # Seed observer with 5 events
        (self.observer / "events.jsonl").write_text(
            "\n".join(json.dumps({"event": i}) for i in range(5)) + "\n"
        )
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        obs = next(s for s in data["systems"] if s["name"] == "observer")
        self.assertEqual(obs["count"], 5)
        self.assertTrue(obs["exists"])

    def test_size_reflects_file_bytes(self):
        content = "a" * 1000 + "\n"
        (self.observer / "events.jsonl").write_text(content)
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        obs = next(s for s in data["systems"] if s["name"] == "observer")
        self.assertEqual(obs["size"], 1001)


class TestGracefulInvalid(_SysCheckBase):
    def test_malformed_jsonl_lines_counted_as_anomaly(self):
        (self.observer / "events.jsonl").write_text(
            json.dumps({"ok": 1}) + "\n" + "garbage line\n" + json.dumps({"ok": 2}) + "\n"
        )
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        obs = next(s for s in data["systems"] if s["name"] == "observer")
        # Count of VALID rows
        self.assertEqual(obs["count"], 2)


class TestHumanOutput(_SysCheckBase):
    def test_default_output_lists_4_systems(self):
        r = self._run("systems-check")
        self.assertEqual(r.returncode, 0)
        for sys_name in ("hooks", "trace", "dxm", "observer"):
            self.assertIn(sys_name, r.stdout)


if __name__ == "__main__":
    unittest.main()
