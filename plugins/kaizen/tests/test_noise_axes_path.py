"""Tests for noise axes' trace-log path resolution.

Asserts each noise axis (hook_cascade / silent_fail / turn_density)
resolves the trace log via _paths.TRACE_FILE (the canonical post-
path_migrate path), not via the hardcoded legacy `~/.claude/.kaizen/
trace/events.jsonl` default that pre-dates the v1.39 path restructure.

Why it matters - the noise axes report "0 events / log not found"
when they look at the legacy path post-migration. /kaizen:metrics
noise rolls up green not because the log is clean but because the
axes can't find it. False-green is worse than yellow.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent


class TestNoiseAxesUseCanonicalTracePath(unittest.TestCase):
    """Each axis must honor KAIZEN_TRACE_DIR (canonical path lookup),
    not fall through to the hardcoded legacy default when the env knob
    is set."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.trace_dir = Path(self._tmp.name) / "indexes" / "trace"
        self.trace_dir.mkdir(parents=True)
        # Seed a real event so an axis would have something to count
        # if it reads this file.
        (self.trace_dir / "events.jsonl").write_text(
            '{"ts":"2026-05-19T00:00:00Z","src":"hook",'
            '"evt":"PreToolUse-bash","tool":"Bash","sid":"test"}\n'
        )
        self._orig = os.environ.get("KAIZEN_TRACE_DIR")
        os.environ["KAIZEN_TRACE_DIR"] = str(self.trace_dir)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_TRACE_DIR", None)
        else:
            os.environ["KAIZEN_TRACE_DIR"] = self._orig

    def _run_axis(self, script: str) -> dict:
        import json
        r = subprocess.run(
            [sys.executable,
             str(_KZ / "scripts" / "quality" / script),
             "gaps", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            self.fail(f"{script} rc={r.returncode}: {r.stderr}")
        return json.loads(r.stdout)

    # Each axis filters events differently (cascade looks at all hook
    # fires; silent_fail looks for PostToolUse w/ empty output;
    # turn_density needs UserPromptSubmit boundaries) — so we don't
    # assert event-counts here. The path-resolution invariant is:
    # the axis FOUND the trace log (note != "trace log not found").

    def test_hook_cascade_finds_canonical_path(self):
        out = self._run_axis("hook_cascade.py")
        note = out.get("data", {}).get("note", "")
        self.assertNotIn("trace log not found", note,
                          f"hook_cascade still reads legacy path: {note}")

    def test_silent_fail_finds_canonical_path(self):
        out = self._run_axis("silent_fail.py")
        note = out.get("data", {}).get("note", "")
        self.assertNotIn("trace log not found", note,
                          f"silent_fail still reads legacy path: {note}")

    def test_turn_density_finds_canonical_path(self):
        out = self._run_axis("turn_density.py")
        note = out.get("data", {}).get("note", "")
        self.assertNotIn("trace log not found", note,
                          f"turn_density still reads legacy path: {note}")


if __name__ == "__main__":
    unittest.main()
