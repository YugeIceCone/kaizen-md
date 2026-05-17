"""TDD — stop-ralph.sh emits a Stop-ralph-iteration trace event per
iteration carrying {action, iteration, pending, completed}.

Ralph brainstorm #5. The existing _trace.sh fires a generic event-name
hit at hook entry; this richer event surfaces what actually happened
that iteration (action / decision / ledger-delta) — enabling
`kaizen-trace search` to answer 'how is the loop progressing?' without
re-parsing state files.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
STOP_HOOK = PLUGIN_ROOT / "hooks" / "claude" / "stop-ralph.sh"


def _write_state(state_path: Path, iteration: int, pending: int,
                   completed: int = 0, session_id: str = "") -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    pending_items = ",".join(
        f'{{"id":"i{i}","desc":"item-{i}","verify":null}}'
        for i in range(1, pending + 1)
    )
    # loop_ledger.py auto-cancels stale state (> 30 days by default);
    # use NOW so the block branch fires instead of complete-empty.
    now_iso = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    completed_items = ",".join(
        f'{{"id":"c{i}","desc":"done-{i}","iteration":1,"completed_at":"{now_iso}"}}'
        for i in range(1, completed + 1)
    )
    state_path.write_text(textwrap.dedent(f"""\
        ---
        active: true
        iteration: {iteration}
        session_id: "{session_id}"
        max_iterations: 30
        completion_promise: null
        started_at: "{now_iso}"
        last_turn_id: ""
        ---
        {{"pending":[{pending_items}],"completed":[{completed_items}]}}
        """))


def _read_trace_events(trace_dir: Path) -> list[dict]:
    f = trace_dir / "events.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


class TestPerIterationTrace(unittest.TestCase):
    def setUp(self):
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        self.trace_dir = self.tmp / "trace"
        self.trace_dir.mkdir()
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_TRACE_DIR"] = str(self.trace_dir)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self._tmpcm.cleanup()

    def _fire_stop(self, state_dir: Path, session_id: str = "sess-1",
                     last_msg: str = "doing work") -> subprocess.CompletedProcess:
        hook_input = json.dumps({
            "session_id": session_id,
            "cwd": str(state_dir),
            "last_assistant_message": last_msg,
            "turn_id": "turn-abc",
        })
        return subprocess.run(
            ["bash", str(STOP_HOOK)],
            input=hook_input, capture_output=True, text=True,
            env=os.environ.copy(), timeout=30,
        )

    def test_block_branch_emits_per_iteration_event(self):
        state_dir = self.tmp / "repo"
        state_dir.mkdir()
        _write_state(state_dir / ".kaizen" / "loop.state.md",
                       iteration=3, pending=2, completed=1,
                       session_id="sess-1")
        proc = self._fire_stop(state_dir, session_id="sess-1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        events = _read_trace_events(self.trace_dir)
        # Must contain the new per-iteration event
        iter_events = [e for e in events if e.get("evt") == "Stop-ralph-iteration"]
        self.assertEqual(len(iter_events), 1,
                          f"expected 1 Stop-ralph-iteration event, got {len(iter_events)}; "
                          f"all events: {[e.get('evt') for e in events]}")
        ev = iter_events[0]
        # data field carries the iteration snapshot
        data = ev.get("data") or {}
        if isinstance(data, str):
            data = json.loads(data)
        self.assertEqual(data.get("iteration"), 3)
        self.assertEqual(data.get("pending"), 2)
        self.assertEqual(data.get("completed"), 1)
        self.assertIn("action", data)

    def test_no_event_when_no_state_file(self):
        """No loop state → hook exits 0 silently, no per-iteration event."""
        state_dir = self.tmp / "norepo"
        state_dir.mkdir()
        proc = self._fire_stop(state_dir)
        self.assertEqual(proc.returncode, 0)
        events = _read_trace_events(self.trace_dir)
        iter_events = [e for e in events if e.get("evt") == "Stop-ralph-iteration"]
        self.assertEqual(len(iter_events), 0)


if __name__ == "__main__":
    unittest.main()
