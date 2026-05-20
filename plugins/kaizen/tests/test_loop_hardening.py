"""Tests for loop-hardening: stale auto-cancel, no-progress detection,
token-saving CLI/MCP accessors.

Run:
    python3 -m unittest tests.test_loop_hardening -v
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import loop_ledger as ll  # noqa: E402
import loop_state as ls  # noqa: E402

SETUP_SCRIPT = PLUGIN_ROOT / "skills" / "loop" / "scripts" / "setup-ralph-loop.sh"

def _write_state(tmp: Path, *, started_at: str = None, body: str = "do work",
                 last_body_sha: str = None, stuck_run: int = 0,
                 max_iter: int = 10, promise: str = "null") -> Path:
    started_at = started_at or dt.datetime.now(dt.timezone.utc).isoformat()
    state_dir = tmp / ".kaizen"
    state_dir.mkdir(exist_ok=True)
    extra_lines = []
    if last_body_sha is not None:
        extra_lines.append(f'last_body_sha: "{last_body_sha}"')
    if stuck_run:
        extra_lines.append(f"stuck_run: {stuck_run}")
    extras = ("\n".join(extra_lines) + "\n") if extra_lines else ""
    state_file = state_dir / "loop.state.md"
    state_file.write_text(
        f'---\nactive: true\niteration: 1\nsession_id: ""\n'
        f'last_turn_id: ""\nmax_iterations: {max_iter}\n'
        f'completion_promise: {promise}\n'
        f'started_at: "{started_at}"\n{extras}---\n{body}\n'
    )
    return state_file

# ─── Stale state auto-cancel ──────────────────────────────────────────

class TestStaleStateAutoCancel(unittest.TestCase):
    def test_fresh_state_is_not_stale(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = _write_state(tmp)  # started "now"
            result = ll.decide(state, 1)
            self.assertNotEqual(result.get("mode"), "stale")
            self.assertEqual(result.get("action"), "block")

    def test_old_state_auto_cancels(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=45)).isoformat()
            state = _write_state(tmp, started_at=old)
            result = ll.decide(state, 1)
            self.assertEqual(result["mode"], "stale")
            self.assertEqual(result["action"], "complete-empty")
            self.assertIn("45d old", result["reason"])

    def test_max_age_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
            state = _write_state(tmp, started_at=old)
            # Default would allow 30-day-old; force a tighter cap
            os.environ["KAIZEN_LOOP_MAX_AGE_DAYS"] = "5"
            try:
                result = ll.decide(state, 1)
            finally:
                del os.environ["KAIZEN_LOOP_MAX_AGE_DAYS"]
            self.assertEqual(result["mode"], "stale")

    def test_malformed_started_at_not_treated_as_stale(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = _write_state(tmp, started_at="not-a-date")
            result = ll.decide(state, 1)
            self.assertNotEqual(result.get("mode"), "stale")

# ─── No-progress detection ────────────────────────────────────────────

class TestNoProgressDetection(unittest.TestCase):
    def test_first_iteration_persists_sha(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = _write_state(tmp, body="initial prompt")
            ll.decide(state, 1)
            text = state.read_text()
            self.assertIn("last_body_sha:", text)
            self.assertIn("stuck_run: 0", text)

    def test_repeated_body_increments_stuck_run(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = _write_state(tmp, body="same prompt")
            ll.decide(state, 1)  # run 0 → 0
            ll.decide(state, 2)  # body sha matched → run 1
            text = state.read_text()
            self.assertIn("stuck_run: 1", text)

    def test_changed_body_resets_stuck_run(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            state = _write_state(tmp, body="prompt v1", stuck_run=3,
                                 last_body_sha="oldsha123")
            result = ll.decide(state, 4)
            # Different body sha → run resets to 0
            self.assertEqual(result.get("stuck_run"), 0)

    def test_auto_cancels_when_stuck_threshold_reached(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            body = "stuck prompt"
            sha = ll._body_sha(body)
            # Pre-set state to indicate 4 prior identical iters; current
            # iter would make it the 5th → trigger threshold.
            state = _write_state(tmp, body=body, last_body_sha=sha, stuck_run=4)
            result = ll.decide(state, 5)
            self.assertEqual(result["mode"], "stuck")
            self.assertEqual(result["action"], "complete-empty")
            self.assertIn("unchanged for 5", result["reason"])

    def test_stuck_threshold_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            body = "stuck prompt"
            sha = ll._body_sha(body)
            state = _write_state(tmp, body=body, last_body_sha=sha, stuck_run=1)
            os.environ["KAIZEN_LOOP_STUCK_ITERATIONS"] = "2"
            try:
                result = ll.decide(state, 2)
            finally:
                del os.environ["KAIZEN_LOOP_STUCK_ITERATIONS"]
            self.assertEqual(result["mode"], "stuck")

# ─── Token-saving accessors ──────────────────────────────────────────

class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()

def _init_ledger_loop(tmpdir: Path, items: list[str], promise: str = "DONE"):
    """Direct file-write — same fix as test_loop_state._init_loop.
    The shell script (setup-ralph-loop.sh) spawns bash + 2× python3
    heredocs which races under 32-process parallel load. This file
    tests the loop_state Python API (next_pending / fail_run / etc.),
    not the shell script — direct seeding preserves test intent.
    """
    state_dir = tmpdir / ".kaizen"
    state_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    for i, raw in enumerate(items, 1):
        if "|" in raw:
            desc, verify = raw.split("|", 1)
            pending.append({"id": f"i{i}", "desc": desc.strip(),
                              "verify": verify.strip() or None})
        else:
            pending.append({"id": f"i{i}", "desc": raw.strip(), "verify": None})
    body = json.dumps({"pending": pending, "completed": []}, indent=2)
    promise_yaml = f'"{promise}"' if promise and promise != "null" else "null"
    (state_dir / "loop.state.md").write_text(
        f"""---
active: true
iteration: 1
session_id:
last_turn_id: ""
max_iterations: 10
completion_promise: {promise_yaml}
started_at: "2026-05-19T00:00:00Z"
---

{body}
""",
        encoding="utf-8")

class TestNextPending(_CwdMixin, unittest.TestCase):
    def test_returns_first_pending(self):
        _init_ledger_loop(self.tmp, ["Implement A|true", "Implement B"])
        item = ls.next_pending()
        self.assertEqual(item["desc"], "Implement A")
        self.assertEqual(item["verify"], "true")

    def test_none_when_no_pending(self):
        # Set up a loop then drain pending by writing empty ledger manually
        _init_ledger_loop(self.tmp, ["A"])
        state_file = self.tmp / ".kaizen" / "loop.state.md"
        # Replace body with empty ledger
        text = state_file.read_text()
        fm, _ = text.split("---\n", 1)[1].rsplit("\n---\n", 1)
        # Easier: directly write a state with empty pending
        import json as _j
        new_state = (
            '---\nactive: true\niteration: 1\nsession_id: ""\n'
            'last_turn_id: ""\nmax_iterations: 5\ncompletion_promise: "DONE"\n'
            'started_at: "2026-05-14T00:00:00Z"\n---\n'
            + _j.dumps({"pending": [], "completed": []}, indent=2)
        )
        state_file.write_text(new_state)
        self.assertIsNone(ls.next_pending())

    def test_none_when_no_loop_active(self):
        self.assertIsNone(ls.next_pending())

class TestProgress(_CwdMixin, unittest.TestCase):
    def test_counters_for_active_loop(self):
        _init_ledger_loop(self.tmp, ["A", "B", "C"])
        p = ls.progress()
        self.assertTrue(p["active"])
        self.assertEqual(p["pending_count"], 3)
        self.assertEqual(p["completed_count"], 0)
        self.assertEqual(p["pct_done"], 0.0)

    def test_inactive_when_no_loop(self):
        p = ls.progress()
        self.assertFalse(p["active"])

class TestTldr(_CwdMixin, unittest.TestCase):
    def test_one_line_summary(self):
        _init_ledger_loop(self.tmp, ["Implement A", "Implement B"])
        line = ls.tldr()
        self.assertIn("iter 1", line)
        self.assertIn("2 pending", line)
        self.assertIn("0 done", line)
        self.assertIn("NEXT: Implement A", line)
        # Compact: under 200 chars
        self.assertLess(len(line), 200)

    def test_empty_string_when_inactive(self):
        self.assertEqual(ls.tldr(), "")

# ─── CLI subcommands (next/progress/tldr) ────────────────────────────

class TestCliAccessors(_CwdMixin, unittest.TestCase):
    HELPER = PLUGIN_ROOT / "scripts" / "state" / "loop_state.py"

    def test_cli_next_returns_first_item(self):
        _init_ledger_loop(self.tmp, ["Implement A", "Implement B"])
        result = subprocess.run(
            ["python3", str(self.HELPER), "next"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Implement A", result.stdout)

    def test_cli_progress_prints_counters(self):
        _init_ledger_loop(self.tmp, ["A", "B"])
        result = subprocess.run(
            ["python3", str(self.HELPER), "progress"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("pending 2", result.stdout)
        self.assertIn("completed 0", result.stdout)

    def test_cli_tldr_one_line(self):
        _init_ledger_loop(self.tmp, ["A"])
        result = subprocess.run(
            ["python3", str(self.HELPER), "tldr"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        # One line of output (plus trailing newline)
        lines = [ln for ln in result.stdout.split("\n") if ln.strip()]
        self.assertEqual(len(lines), 1)

    def test_cli_next_exits_nonzero_when_empty(self):
        result = subprocess.run(
            ["python3", str(self.HELPER), "next"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)

if __name__ == "__main__":
    unittest.main()
