"""Tests for posttool-observer-capture — Phase 1.5 of the observer.

The clever-lama-mcp side has ingest_event() that knows the canonical
event shape (per docs/superpowers/specs/2026-05-18-custom-observer-
design.md). This hook lives on the kaizen-md side (hooks belong to the
plugin per the 13-slot shape) and writes minimally-shaped events to
the same sink. Standalone — no cross-repo import.

Design contract (same as detect-nudge):
  - PROGRAMMABLE  — pure-function core (normalize_cc_event + capture)
  - REPRODUCIBLE  — deterministic output for given input + now
  - CONSISTENT    — env-overridable sink, atomic append, exit 0 always
  - DETERMINISTIC — `now` is parameter
  - REUSABLE      — works for any PostToolUse event shape; tool-name
                     and source mapping table is a registry
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HOOKS = Path(__file__).resolve().parent.parent / "hooks" / "claude"
sys.path.insert(0, str(_HOOKS))

import _observer_capture as oc  # noqa: E402


_T0 = "2026-05-18T20:00:00Z"


def _stdin(tool_name: str, file_path: str | None = None,
            sid: str = "sess-test", **extra) -> str:
    payload: dict = {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path} if file_path else {},
        "session_id": sid,
    }
    payload.update(extra)
    return json.dumps(payload)


class TestNormalize:
    def test_pre_tool_use_event_kind(self):
        evt = oc.normalize_cc_event(
            _stdin("Read", "/a.py"),
            event_kind="pre_tool_use",
            now=_T0,
        )
        assert evt["event_kind"] == "pre_tool_use"
        assert evt["source"] == "parent"  # default; subagent detected via env
        assert evt["sid"] == "sess-test"
        assert evt["tool"] == "Read"
        assert evt["ts"] == _T0
        assert evt["params"]["file_path"] == "/a.py"

    def test_post_tool_use_event_kind(self):
        evt = oc.normalize_cc_event(
            _stdin("Edit", "/b.py"),
            event_kind="post_tool_use",
            now=_T0,
        )
        assert evt["event_kind"] == "post_tool_use"
        assert evt["tool"] == "Edit"

    def test_mcp_tool_call_event_kind_detected(self):
        evt = oc.normalize_cc_event(
            _stdin("mcp__clever-lama__parallel_subagents"),
            event_kind="post_tool_use",
            now=_T0,
        )
        # mcp__ prefix detection → event_kind upgraded to mcp_tool_call
        assert evt["event_kind"] == "mcp_tool_call"
        assert evt["mcp_server"] == "clever-lama"
        assert evt["tool"] == "mcp__clever-lama__parallel_subagents"

    def test_subagent_source_via_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_SUBAGENT_TYPE", "kaizen:kaizen-implementer")
        evt = oc.normalize_cc_event(
            _stdin("Read", "/a.py"),
            event_kind="pre_tool_use",
            now=_T0,
        )
        assert evt["source"] == "subagent"
        assert evt["subagent_type"] == "kaizen:kaizen-implementer"

    def test_garbage_stdin_returns_none(self):
        assert oc.normalize_cc_event("not json{", event_kind="pre_tool_use",
                                       now=_T0) is None
        assert oc.normalize_cc_event("", event_kind="pre_tool_use",
                                       now=_T0) is None

    def test_idempotent_replay(self):
        """Reproducibility — same inputs always produce same output dict."""
        a = oc.normalize_cc_event(_stdin("Read", "/a.py"),
                                    event_kind="post_tool_use", now=_T0)
        b = oc.normalize_cc_event(_stdin("Read", "/a.py"),
                                    event_kind="post_tool_use", now=_T0)
        assert a == b


class TestCapture:
    def test_appends_to_sink(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAIZEN_OBSERVER_DIR", str(tmp_path))
        result = oc.capture(_stdin("Read", "/a.py"),
                              event_kind="pre_tool_use", now=_T0)
        assert result["ok"]
        sink = tmp_path / "events.jsonl"
        assert sink.is_file()
        lines = sink.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tool"] == "Read"
        assert entry["event_kind"] == "pre_tool_use"

    def test_multiple_captures_append(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAIZEN_OBSERVER_DIR", str(tmp_path))
        for i in range(3):
            oc.capture(_stdin("Read", f"/f{i}.py"),
                         event_kind="pre_tool_use", now=_T0)
        lines = (tmp_path / "events.jsonl").read_text().splitlines()
        assert len(lines) == 3

    def test_garbage_input_does_not_crash_does_not_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAIZEN_OBSERVER_DIR", str(tmp_path))
        result = oc.capture("not-json{", event_kind="pre_tool_use", now=_T0)
        assert not result["ok"]
        sink = tmp_path / "events.jsonl"
        # Either no file at all, or empty
        if sink.exists():
            assert sink.read_text().strip() == ""

    def test_disable_env_skips_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAIZEN_OBSERVER_DIR", str(tmp_path))
        monkeypatch.setenv("KAIZEN_OBSERVER_DISABLE", "1")
        result = oc.capture(_stdin("Read", "/a.py"),
                              event_kind="pre_tool_use", now=_T0)
        assert not result["ok"]
        sink = tmp_path / "events.jsonl"
        assert not sink.exists()

    def test_append_cost_constant_on_large_sink(self, tmp_path, monkeypatch):
        """Constant-cost append — proves append-only (no read-then-overwrite).
        Same proof pattern as kaizen-progress + kaizen-learn."""
        monkeypatch.setenv("KAIZEN_OBSERVER_DIR", str(tmp_path))
        sink = tmp_path / "events.jsonl"
        # Seed with 500 small events
        for i in range(500):
            oc.capture(_stdin("Read", f"/path-{i}.py"),
                         event_kind="pre_tool_use", now=_T0)
        size_before = sink.stat().st_size
        assert size_before > 30_000
        oc.capture(_stdin("Write", "/extra.py"),
                     event_kind="post_tool_use", now=_T0)
        size_after = sink.stat().st_size
        delta = size_after - size_before
        assert delta < 400, (
            f"append delta={delta}B; expected <400B (one event). "
            "If this fails, capture is read-then-overwriting."
        )
