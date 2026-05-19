"""Tests for the roundtrip-detect hook core.

The hook runs on every PostToolUse. It watches for canonical waste patterns:
  - Read PATH then Edit/Write same PATH within N seconds → roundtrip
    (the Read+Edit dance kaizen-progress was built to eliminate)

When detected, emits an `additionalContext` JSON line to stdout suggesting
the agent run `kaizen-learn append --category roundtrips ...` with
context about what was observed.

The core is a PURE FUNCTION over (input_event, current_state, now,
window_seconds) -> (new_state, optional_nudge_text). Reproducible:
same inputs always produce same outputs. No randomness, no wall-clock
peek — `now` is passed in (production: extract from event payload or
inject; tests: pass fixed values).

Hook contract: exit 0 always; emit nudge via stdout JSON; never block.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Adjust import path — hook lives in hooks/claude/, tests in tests/
_HOOKS = Path(__file__).resolve().parent.parent / "hooks" / "claude"
sys.path.insert(0, str(_HOOKS))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "handlers"))

import _roundtrip_detect as rd  # noqa: E402


_T0 = "2026-05-18T20:00:00Z"
_T_PLUS_10 = "2026-05-18T20:00:10Z"
_T_PLUS_45 = "2026-05-18T20:00:45Z"
_T_PLUS_120 = "2026-05-18T20:02:00Z"


def _evt(tool: str, path: str, ts: str = _T0) -> dict:
    return {
        "ts": ts,
        "tool_name": tool,
        "tool_input": {"file_path": path},
    }


class TestPureFunctionCore:
    """Each test calls rd.process_event directly — no subprocess, no I/O."""

    def test_read_then_edit_same_path_within_window_nudges(self):
        state = {}
        # Read first
        state, nudge = rd.process_event(_evt("Read", "/a.py", _T0),
                                          state, window_seconds=30)
        assert nudge is None
        # Edit within window
        state, nudge = rd.process_event(_evt("Edit", "/a.py", _T_PLUS_10),
                                          state, window_seconds=30)
        assert nudge is not None
        assert "roundtrips" in nudge
        assert "/a.py" in nudge

    def test_edit_outside_window_no_nudge(self):
        state = {}
        state, _ = rd.process_event(_evt("Read", "/a.py", _T0),
                                      state, window_seconds=30)
        state, nudge = rd.process_event(_evt("Edit", "/a.py", _T_PLUS_120),
                                          state, window_seconds=30)
        assert nudge is None

    def test_different_paths_no_nudge(self):
        state = {}
        state, _ = rd.process_event(_evt("Read", "/a.py", _T0),
                                      state, window_seconds=30)
        state, nudge = rd.process_event(_evt("Edit", "/b.py", _T_PLUS_10),
                                          state, window_seconds=30)
        assert nudge is None

    def test_write_after_read_also_nudges(self):
        """Write is the same anti-pattern as Edit (overwrite after read)."""
        state = {}
        state, _ = rd.process_event(_evt("Read", "/a.py", _T0),
                                      state, window_seconds=30)
        state, nudge = rd.process_event(_evt("Write", "/a.py", _T_PLUS_10),
                                          state, window_seconds=30)
        assert nudge is not None
        assert "/a.py" in nudge

    def test_edit_only_no_nudge(self):
        state = {}
        state, nudge = rd.process_event(_evt("Edit", "/a.py", _T0),
                                          state, window_seconds=30)
        assert nudge is None

    def test_idempotent_replay_same_inputs_same_outputs(self):
        """Reproducibility — same input sequence yields identical (state, nudge)
        outputs across runs. The whole point per the user's directive."""
        seq = [_evt("Read", "/a.py", _T0), _evt("Edit", "/a.py", _T_PLUS_10)]

        state_a, nudges_a = {}, []
        for e in seq:
            state_a, n = rd.process_event(e, state_a, window_seconds=30)
            nudges_a.append(n)

        state_b, nudges_b = {}, []
        for e in seq:
            state_b, n = rd.process_event(e, state_b, window_seconds=30)
            nudges_b.append(n)

        assert state_a == state_b
        assert nudges_a == nudges_b

    def test_window_at_exact_boundary_no_nudge(self):
        """30-second window: an Edit at exactly +30s is OUTSIDE (strict <)."""
        state = {}
        state, _ = rd.process_event(_evt("Read", "/a.py", _T0),
                                      state, window_seconds=30)
        # Exactly +30s → boundary
        state, nudge = rd.process_event(
            _evt("Edit", "/a.py", "2026-05-18T20:00:30Z"),
            state, window_seconds=30
        )
        assert nudge is None

    def test_pruning_old_state(self):
        """State must not grow unbounded — entries older than the window get
        pruned so memory stays constant for long-running sessions."""
        state = {}
        # Seed 100 reads on different paths, far in the past
        for i in range(100):
            state, _ = rd.process_event(
                _evt("Read", f"/old-{i}.py", _T0),
                state, window_seconds=30,
            )
        # Now make a fresh read — old entries should have been pruned
        # since they're outside the window
        state, _ = rd.process_event(
            _evt("Read", "/new.py", _T_PLUS_120),
            state, window_seconds=30,
        )
        # Only the fresh read survives (everything else was pruned)
        assert len(state) == 1, f"state should prune to 1 entry, got {len(state)}"
        assert "/new.py" in state


class TestRunHookEntry:
    """rd.run_hook is the subprocess-style entry — takes JSON-string stdin
    + state path, returns the stdout dict + new state. Same purity contract."""

    def test_run_hook_returns_envelope_when_nudge_fires(self, tmp_path):
        import json
        state_path = tmp_path / "state.json"

        # First call: Read
        stdin = json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/a.py"},
            "ts": _T0,
        })
        out, _ = rd.run_hook(stdin, state_path=state_path,
                              window_seconds=30, now=_T0)
        assert "hookSpecificOutput" not in out  # no nudge yet

        # Second call: Edit within window
        stdin = json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/a.py"},
            "ts": _T_PLUS_10,
        })
        out, _ = rd.run_hook(stdin, state_path=state_path,
                              window_seconds=30, now=_T_PLUS_10)
        assert out.get("hookSpecificOutput", {}).get("hookEventName") == "PostToolUse"
        assert "roundtrips" in out["hookSpecificOutput"]["additionalContext"]

    def test_run_hook_garbage_input_no_crash(self, tmp_path):
        out, _ = rd.run_hook("not json{", state_path=tmp_path / "s.json",
                              window_seconds=30, now=_T0)
        assert out == {}  # No nudge; empty envelope; doesn't crash

    def test_run_hook_state_file_missing_first_run(self, tmp_path):
        import json
        sp = tmp_path / "fresh.json"
        assert not sp.exists()
        stdin = json.dumps({
            "tool_name": "Read",
            "tool_input": {"file_path": "/a.py"},
            "ts": _T0,
        })
        out, _ = rd.run_hook(stdin, state_path=sp,
                              window_seconds=30, now=_T0)
        assert out == {}  # no nudge on first event ever
        assert sp.is_file()  # state file created


class TestBypassEnv:
    """KAIZEN_LEARNING_DETECT_DISABLE=1 → no-op."""

    def test_disable_env_skips_all_processing(self, tmp_path, monkeypatch):
        import json
        monkeypatch.setenv("KAIZEN_LEARNING_DETECT_DISABLE", "1")
        sp = tmp_path / "s.json"

        # Even a sequence that would nudge → no nudge when disabled
        for evt in [
            {"tool_name": "Read", "tool_input": {"file_path": "/a.py"}, "ts": _T0},
            {"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}, "ts": _T_PLUS_10},
        ]:
            out, _ = rd.run_hook(json.dumps(evt), state_path=sp,
                                  window_seconds=30, now=evt["ts"])
            assert "hookSpecificOutput" not in out

        # State file should also not be touched
        assert not sp.exists()
