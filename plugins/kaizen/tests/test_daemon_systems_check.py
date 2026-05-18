"""Tests for `kaizen-daemon systems-check` — periodic ping of runtime systems.

Per user 2026-05-18 — "all system can start and be on a keep-alive timer
on the claude code session start api." Plus follow-up "trace kaizen
daemon watcher heartbeat systems" + "audit heartbeat system surface".

Tracked systems (after audit 2026-05-18-kaizen-md-9f4c8972):
  hooks           — hooks/hooks.json wiring (config; not a sink)
  trace           — ~/.claude/.kaizen/indexes/trace/events.jsonl
  dxm             — ~/.claude/.kaizen/dxm/events-<sid>.jsonl
  observer        — ~/.claude/.kaizen/observer/events.jsonl
  learning        — ~/.claude/.kaizen/learning/events.jsonl
  keepalive-meta  — ~/.claude/.kaizen/keepalive/counter.txt (the counter file)
  daemon-watcher  — ~/.claude/.kaizen/data/daemon/watcher.pid (pid file)
  handoff-db      — ~/.claude/.kaizen/data/handoff.db (sqlite size+mtime)

Per-system check:
  exists, size, last_mtime, count (jsonl lines), stale (bool)

`stale` is true when last_mtime is older than KAIZEN_KEEPALIVE_STALE_SEC
(default 7200 = 2h). Informational only — never blocks.

Output: heartbeat row appended to <KAIZEN_KEEPALIVE_DIR>/heartbeat.jsonl.
Rotated to .1 when file > KAIZEN_KEEPALIVE_ROTATE_BYTES (default 1MB).
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
        # Sandbox the 5 sink/meta dirs + 1 handoff db via env
        self.observer = self.tmp / "observer"
        self.dxm = self.tmp / "dxm"
        self.trace = self.tmp / "trace"
        self.learning = self.tmp / "learning"
        self.keepalive = self.tmp / "keepalive"
        self.daemon = self.tmp / "data" / "daemon"
        self.data = self.tmp / "data"
        for d in (self.observer, self.dxm, self.trace, self.learning,
                  self.keepalive, self.daemon, self.data):
            d.mkdir(parents=True, exist_ok=True)
        self.handoff_db = self.data / "handoff.db"
        # Pre-test env state
        self._orig = {}
        for k, v in (
            ("KAIZEN_OBSERVER_DIR", str(self.observer)),
            ("KAIZEN_DXM_DIR", str(self.dxm)),
            ("KAIZEN_TRACE_DIR", str(self.trace)),
            ("KAIZEN_LEARNING_DIR", str(self.learning)),
            ("KAIZEN_KEEPALIVE_DIR", str(self.keepalive)),
            ("KAIZEN_DAEMON_DIR", str(self.daemon)),
            ("KAIZEN_HANDOFF_DB", str(self.handoff_db)),
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


_EXPECTED_NAMES = {"hooks", "trace", "dxm", "observer",
                     "learning", "keepalive-meta",
                     "daemon-watcher", "handoff-db"}
# Note: 'gold' deferred — per-project sink at gold/<project-slug>/patterns.jsonl
# needs glob-walk probe shape (separate kind, future iteration).


class TestSystemsCheckEmpty(_SysCheckBase):
    def test_no_sinks_returns_per_system_zero_state(self):
        r = self._run("systems-check", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("systems", data)
        names = {s["name"] for s in data["systems"]}
        self.assertEqual(names, _EXPECTED_NAMES)
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
    def test_default_output_lists_all_systems(self):
        r = self._run("systems-check")
        self.assertEqual(r.returncode, 0)
        for sys_name in _EXPECTED_NAMES:
            self.assertIn(sys_name, r.stdout)


class TestStalenessFlag(_SysCheckBase):
    def test_fresh_sink_not_stale(self):
        # Just-written file => stale: False
        (self.learning / "log.jsonl").write_text('{"x":1}\n')
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        learning = next(s for s in data["systems"] if s["name"] == "learning")
        self.assertTrue(learning["exists"])
        self.assertFalse(learning.get("stale", True))

    def test_old_mtime_flagged_stale(self):
        # Write a file then back-date its mtime to 3h ago (>2h default threshold)
        p = self.learning / "log.jsonl"
        p.write_text('{"x":1}\n')
        import time as _t
        old_t = _t.time() - 3 * 3600
        os.utime(p, (old_t, old_t))
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        learning = next(s for s in data["systems"] if s["name"] == "learning")
        self.assertTrue(learning["stale"])

    def test_threshold_overridable_via_env(self):
        # Set a 60s threshold; write a file, back-date 5 min, expect stale
        p = self.learning / "log.jsonl"
        p.write_text('{"y":2}\n')
        import time as _t
        os.utime(p, (_t.time() - 300, _t.time() - 300))
        env = os.environ.copy()
        env["KAIZEN_KEEPALIVE_STALE_SEC"] = "60"
        r = subprocess.run([sys.executable, str(_DAEMON), "systems-check", "--json"],
                            capture_output=True, text=True, timeout=15, env=env)
        data = json.loads(r.stdout)
        learning = next(s for s in data["systems"] if s["name"] == "learning")
        self.assertTrue(learning["stale"])

    def test_absent_sink_not_stale(self):
        # exists=False => stale should be False (nothing to be stale about)
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        observer = next(s for s in data["systems"] if s["name"] == "observer")
        self.assertFalse(observer["exists"])
        self.assertFalse(observer.get("stale", True))


class TestHeartbeatRotation(_SysCheckBase):
    def test_no_rotation_below_threshold(self):
        # Default 1MB threshold; single tiny row stays unrotated
        self._run("systems-check")
        rotated = self.keepalive / "heartbeat.jsonl.1"
        self.assertFalse(rotated.is_file())

    def test_rotation_triggers_above_threshold(self):
        # Seed a large heartbeat.jsonl then call once; rotation moves to .1
        hb = self.keepalive / "heartbeat.jsonl"
        hb.write_text("x" * (2 * 1024 * 1024))  # 2MB > 1MB default
        self._run("systems-check")
        self.assertTrue((self.keepalive / "heartbeat.jsonl.1").is_file())
        # New file exists too (just appended this call)
        self.assertTrue(hb.is_file())

    def test_rotation_threshold_overridable(self):
        # 100-byte threshold makes rotation fire after first tiny seed
        hb = self.keepalive / "heartbeat.jsonl"
        hb.write_text("x" * 200)  # 200 bytes > 100 threshold
        env = os.environ.copy()
        env["KAIZEN_KEEPALIVE_ROTATE_BYTES"] = "100"
        subprocess.run([sys.executable, str(_DAEMON), "systems-check"],
                        capture_output=True, text=True, timeout=15, env=env)
        self.assertTrue((self.keepalive / "heartbeat.jsonl.1").is_file())


class TestPidSystem(_SysCheckBase):
    def test_pid_file_existence(self):
        # daemon-watcher kind="pid"; exists=True when pid file present
        pid_file = self.daemon / "watcher.pid"
        pid_file.write_text("12345\n")
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        watcher = next(s for s in data["systems"] if s["name"] == "daemon-watcher")
        self.assertTrue(watcher["exists"])
        self.assertEqual(watcher["kind"], "pid")

    def test_pid_absent(self):
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        watcher = next(s for s in data["systems"] if s["name"] == "daemon-watcher")
        self.assertFalse(watcher["exists"])


class TestDbSystem(_SysCheckBase):
    def test_handoff_db_size_reported(self):
        self.handoff_db.write_bytes(b"sqlite3-header-stub" + b"\0" * 100)
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        h = next(s for s in data["systems"] if s["name"] == "handoff-db")
        self.assertTrue(h["exists"])
        self.assertEqual(h["kind"], "db")
        self.assertGreater(h["size"], 0)

    def test_handoff_db_absent(self):
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        h = next(s for s in data["systems"] if s["name"] == "handoff-db")
        self.assertFalse(h["exists"])


class TestKeepaliveMeta(_SysCheckBase):
    def test_counter_file_probed(self):
        (self.keepalive / "counter.txt").write_text("17\n")
        r = self._run("systems-check", "--json")
        data = json.loads(r.stdout)
        m = next(s for s in data["systems"] if s["name"] == "keepalive-meta")
        self.assertTrue(m["exists"])


if __name__ == "__main__":
    unittest.main()
