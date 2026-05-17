"""Tests for the statusline dxm segment renderer.

A small Python tool `statusline_dxm.py` reads dxm state for the
active session and prints one line for the statusline. Designed to
render in <50ms (the statusline budget).
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
_STATUSLINE = _SCRIPTS / "statusline_dxm.py"


class StatuslineDxmBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        self.dxm_dir = self.tmp / "dxm"
        self.dxm_dir.mkdir()

        self._orig: dict[str, str | None] = {}
        for k, v in (("HOME", str(self.fake_home)),
                      ("KAIZEN_DXM_DIR", str(self.dxm_dir))):
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _run(self, *args: str, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_STATUSLINE), *args],
            capture_output=True, text=True, timeout=5,
            cwd=str(cwd) if cwd else None,
            env=os.environ.copy(),
        )

    def _seed_project(self, cwd: Path, sid: str) -> Path:
        """Create ~/.claude/projects/<slug>/<sid>.jsonl so session-id
        discovery works for this cwd."""
        slug = str(cwd.resolve()).replace("/", "-")
        proj = self.fake_home / ".claude" / "projects" / slug
        proj.mkdir(parents=True)
        (proj / f"{sid}.jsonl").write_text("{}\n")
        return proj

    def _seed_dxm_events(self, sid: str, count: int, tool: str = "Bash"):
        # Direct file write — faster than spawning dxm capture
        events_file = self.dxm_dir / f"events-{sid}.jsonl"
        with events_file.open("a") as f:
            for i in range(count):
                f.write(json.dumps({
                    "ts_unix": time.time() - (count - i) * 0.01,
                    "session_id": sid,
                    "evt_type": "PreToolUse",
                    "tool_name": tool,
                }) + "\n")


# ─── Default output: events + lag ────────────────────────────────────


class TestSegmentOutput(StatuslineDxmBase):
    def test_emits_event_count_and_lag(self):
        cwd = self.tmp / "p"
        cwd.mkdir()
        self._seed_project(cwd, "sess-sl")
        self._seed_dxm_events("sess-sl", 5)
        r = self._run(cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.strip()
        # Expected shape: "dxm: 5ev/Xs"
        self.assertTrue(out.startswith("dxm:"),
                          f"unexpected segment: {out!r}")
        self.assertIn("5ev", out)
        self.assertRegex(out, r"\d+(\.\d+)?s")  # lag like "0.05s" or "12s"

    def test_no_session_returns_empty_string(self):
        """When no session JSONL exists for cwd, segment is empty
        (statusline drops it from the composition)."""
        cwd = self.tmp / "no-project"
        cwd.mkdir()
        r = self._run(cwd=cwd)
        # Empty output → statusline.sh drops the segment
        self.assertEqual(r.stdout.strip(), "")

    def test_no_dxm_events_for_session_returns_empty(self):
        cwd = self.tmp / "p-empty"
        cwd.mkdir()
        self._seed_project(cwd, "sess-empty")
        # No dxm events file
        r = self._run(cwd=cwd)
        self.assertEqual(r.stdout.strip(), "")


class TestSegmentWithToolBreakdown(StatuslineDxmBase):
    def test_top_tool_in_segment(self):
        """When --show-top is passed, the most-used tool surfaces."""
        cwd = self.tmp / "p2"
        cwd.mkdir()
        self._seed_project(cwd, "sess-top")
        self._seed_dxm_events("sess-top", 5, tool="Bash")
        self._seed_dxm_events("sess-top", 2, tool="Edit")
        r = self._run("--show-top", cwd=cwd)
        out = r.stdout.strip()
        # Format: "dxm: 7ev/Xs Bash:5"
        self.assertIn("Bash:5", out)


class TestSegmentRolling(StatuslineDxmBase):
    def test_back_seconds_filter(self):
        """--back N filters to events in last N seconds."""
        cwd = self.tmp / "p3"
        cwd.mkdir()
        self._seed_project(cwd, "sess-rolling")
        # Seed 5 events well in the past
        events_file = self.dxm_dir / "events-sess-rolling.jsonl"
        with events_file.open("a") as f:
            for i in range(5):
                f.write(json.dumps({
                    "ts_unix": time.time() - 3600,  # 1 hour ago
                    "session_id": "sess-rolling",
                    "evt_type": "PreToolUse",
                    "tool_name": "Bash",
                }) + "\n")
        # Then 2 fresh events
        with events_file.open("a") as f:
            for i in range(2):
                f.write(json.dumps({
                    "ts_unix": time.time() - 1,
                    "session_id": "sess-rolling",
                    "evt_type": "PreToolUse",
                    "tool_name": "Bash",
                }) + "\n")
        r = self._run("--back", "60", cwd=cwd)
        out = r.stdout.strip()
        # Only the 2 fresh ones in the last 60s
        self.assertIn("2ev", out)


class TestSegmentDisabled(StatuslineDxmBase):
    def test_disable_env_returns_empty(self):
        cwd = self.tmp / "p4"
        cwd.mkdir()
        self._seed_project(cwd, "sess-disable")
        self._seed_dxm_events("sess-disable", 3)
        os.environ["KAIZEN_DXM_DISABLE"] = "1"
        try:
            r = self._run(cwd=cwd)
            self.assertEqual(r.stdout.strip(), "")
        finally:
            del os.environ["KAIZEN_DXM_DISABLE"]


class TestSegmentLatency(StatuslineDxmBase):
    def test_renders_under_500ms(self):
        """Statusline budget is <50ms but we allow 500ms for the
        subprocess overhead in tests (Python startup ≈300ms)."""
        cwd = self.tmp / "p5"
        cwd.mkdir()
        self._seed_project(cwd, "sess-perf")
        self._seed_dxm_events("sess-perf", 100)
        t0 = time.time()
        r = self._run(cwd=cwd)
        elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0)
        self.assertLess(elapsed, 0.5,
                          f"segment took {elapsed:.3f}s — too slow")


if __name__ == "__main__":
    unittest.main()
