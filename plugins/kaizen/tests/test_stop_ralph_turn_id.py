"""Regression — stop-ralph.sh per-turn idempotence must work within ONE
CC session.

The bug: CC's Stop event omits `turn_id`; the script previously fell
back to `transcript_path` which is stable for the entire session, so
the very first Stop set `last_turn_id` and EVERY subsequent Stop in
the same session matched the idempotence guard → permanent
"Ralph loop already processed this turn" until the state file was
manually deleted.

Fix: synthesize a per-turn key from sha1(last_assistant_message) when
turn_id is absent. Different assistant outputs → different keys → no
false idempotence collision.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/stop-ralph.sh"


def _run_hook(cwd: Path, hook_input: dict) -> tuple[int, str, str]:
    """Invoke the Stop hook with a JSON payload on stdin; return rc + stdout + stderr."""
    proc = subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(hook_input),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_KZ_DIR)},
    )
    return proc.returncode, proc.stdout, proc.stderr


def _seed_loop_state(cwd: Path, *, last_turn_id: str = "") -> Path:
    """Create a minimal active loop.state.md inside cwd/.kaizen/."""
    state = cwd / ".kaizen" / "loop.state.md"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(textwrap.dedent(f"""\
        ---
        active: true
        iteration: 1
        session_id: ""
        last_turn_id: "{last_turn_id}"
        max_iterations: 0
        completion_promise: null
        started_at: "2026-05-17T00:00:00Z"
        ---
        complete the task
        """))
    return state


class TestStopRalphPerTurnIdempotence(unittest.TestCase):
    """The script must NOT emit 'already processed' across two
    different assistant turns within the same session."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_different_turns_no_false_idempotence(self):
        """Bug repro — same session, same transcript_path, but two
        DIFFERENT assistant messages. Pre-fix: 2nd hook fired
        'already processed' because last_turn_id matched the
        transcript_path from the 1st fire. Post-fix: the per-turn
        sha1 of last_assistant_message changes per turn."""
        _seed_loop_state(self.cwd)
        common = {
            "session_id": "sess-A",
            "cwd": str(self.cwd),
            "transcript_path": "/some/stable/path/to/transcript.jsonl",
        }
        # Turn 1
        rc1, out1, _ = _run_hook(self.cwd, {
            **common, "last_assistant_message": "first turn output"})
        # Turn 2 — DIFFERENT message
        rc2, out2, _ = _run_hook(self.cwd, {
            **common, "last_assistant_message": "second turn output"})

        # Neither should emit "already processed".
        for label, out in (("turn1", out1), ("turn2", out2)):
            self.assertNotIn(
                "already processed this turn", out,
                f"{label} wrongly flagged as duplicate: {out!r}",
            )

    def test_same_turn_repeated_fire_is_idempotent(self):
        """Refire-protection still works when the assistant message
        is identical (CC really did fire the hook twice for the same
        turn — the legitimate case the original code was guarding)."""
        _seed_loop_state(self.cwd)
        payload = {
            "session_id": "sess-B",
            "cwd": str(self.cwd),
            "transcript_path": "/another/transcript.jsonl",
            "last_assistant_message": "same output text",
        }
        # First fire — should NOT say "already processed".
        _, out1, _ = _run_hook(self.cwd, payload)
        # Second fire — SHOULD say "already processed" (refire-guard).
        _, out2, _ = _run_hook(self.cwd, payload)
        self.assertNotIn("already processed this turn", out1)
        self.assertIn("already processed this turn", out2,
                       "second identical fire must be idempotent")


if __name__ == "__main__":
    unittest.main()
