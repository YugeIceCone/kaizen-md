"""Tests for _dxm_emit.py — shared dxm event emitter.

DRY/SOLID/KISS:
- DRY: single source of session-id discovery + JSON build + append.
  No handler reimplements the flow.
- SOLID-SRP: emit_event does ONE thing — write a dxm event.
  Handlers do their work; emit is pulled out.
- KISS: one function, ~30 LOC, best-effort, never raises.

Used by handoff (verify/scaffold/create/assess/auto-finalize) and
intent (match/suggest/scan) handlers to record per-subcommand
completion events into the dxm event stream.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 — adds scripts/<cluster>/ to sys.path


class EmitBase(unittest.TestCase):
    def setUp(self):
        # Save cwd BEFORE creating tempdir so tearDown can restore even
        # if a test chdir'd into the tempdir (which we then delete).
        self._cwd0 = os.getcwd()
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
        # Restore cwd FIRST — must happen before tempdir is deleted
        # else subsequent tests see "current directory doesn't exist"
        # from any Path(".").resolve() call.
        try:
            os.chdir(self._cwd0)
        except OSError:
            pass
        self._tmp.cleanup()
        for k, v in self._orig.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def _seed_project(self, cwd: Path, sid: str):
        slug = str(cwd.resolve()).replace("/", "-")
        (self.fake_home / ".claude" / "projects" / slug).mkdir(parents=True)
        (self.fake_home / ".claude" / "projects" / slug / f"{sid}.jsonl").write_text("{}\n")

    def _read_events(self, sid: str) -> list[dict]:
        p = self.dxm_dir / f"events-{sid}.jsonl"
        if not p.is_file(): return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


class TestExplicitSessionId(EmitBase):
    def test_emit_writes_event_to_per_session_jsonl(self):
        from _dxm_emit import emit_event
        ok = emit_event("test.evt", session_id="sess-explicit")
        self.assertTrue(ok)
        events = self._read_events("sess-explicit")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["evt_type"], "test.evt")
        self.assertEqual(events[0]["session_id"], "sess-explicit")
        self.assertIn("ts_unix", events[0])

    def test_tool_name_preserved(self):
        from _dxm_emit import emit_event
        emit_event("x", session_id="s1", tool_name="kaizen-handoff")
        events = self._read_events("s1")
        self.assertEqual(events[0].get("tool_name"), "kaizen-handoff")

    def test_payload_preserved(self):
        from _dxm_emit import emit_event
        emit_event("y", session_id="s2",
                    payload={"verdict": "clean", "count": 5})
        events = self._read_events("s2")
        self.assertEqual(events[0].get("payload"),
                          {"verdict": "clean", "count": 5})


class TestAutoDiscoverSessionId(EmitBase):
    def test_emit_auto_discovers_from_cwd(self):
        from _dxm_emit import emit_event
        cwd = self.tmp / "proj"
        cwd.mkdir()
        self._seed_project(cwd, "sess-auto")
        # No explicit session_id — should discover via cwd → slug
        os.chdir(str(cwd))
        try:
            ok = emit_event("test.auto")
        finally:
            os.chdir(str(self.tmp))
        self.assertTrue(ok)
        events = self._read_events("sess-auto")
        self.assertEqual(events[0]["evt_type"], "test.auto")

    def test_no_session_id_no_project_returns_false(self):
        from _dxm_emit import emit_event
        cwd = self.tmp / "no-proj"
        cwd.mkdir()
        os.chdir(str(cwd))
        try:
            ok = emit_event("test.nosession")
        finally:
            os.chdir(str(self.tmp))
        self.assertFalse(ok)


class TestDisableBypass(EmitBase):
    def test_disable_env_returns_false_no_write(self):
        from _dxm_emit import emit_event
        os.environ["KAIZEN_DXM_DISABLE"] = "1"
        try:
            ok = emit_event("test.disabled", session_id="sd")
        finally:
            del os.environ["KAIZEN_DXM_DISABLE"]
        self.assertFalse(ok)
        # No file created
        self.assertFalse((self.dxm_dir / "events-sd.jsonl").exists())


class TestNeverRaises(EmitBase):
    def test_write_to_unwritable_path_returns_false(self):
        from _dxm_emit import emit_event
        # Point KAIZEN_DXM_DIR at a path that can't be created
        os.environ["KAIZEN_DXM_DIR"] = "/proc/should-not-write"
        try:
            ok = emit_event("test.unwritable", session_id="sx")
        finally:
            os.environ["KAIZEN_DXM_DIR"] = str(self.dxm_dir)
        # Best-effort: returns False, doesn't raise
        self.assertFalse(ok)

    def test_invalid_payload_type_handled(self):
        from _dxm_emit import emit_event
        # Non-serializable object — JSON will fall back to default=str
        ok = emit_event("test.objpayload", session_id="sj",
                         payload={"obj": object()})
        # Either True (default=str converted it) or False (graceful)
        # — never raises
        self.assertIsInstance(ok, bool)


class TestEmitSubcommandComplete(EmitBase):
    """Convenience helper for the handler-completion pattern.
    Centralizes the 'kaizen-<tool>' + '<tool>.<sub>.complete' naming
    convention across 8 callers (handoff verify/scaffold/create/
    assess/auto-finalize + intent match/suggest/scan)."""

    def test_writes_canonical_event_shape(self):
        from _dxm_emit import emit_subcommand_complete
        ok = emit_subcommand_complete("handoff", "verify",
                                       payload={"verdict": "clean"},
                                       session_id="sub-test")
        self.assertTrue(ok)
        events = self._read_events("sub-test")
        self.assertEqual(events[0]["evt_type"], "handoff.verify.complete")
        self.assertEqual(events[0]["tool_name"], "kaizen-handoff")
        self.assertEqual(events[0]["payload"], {"verdict": "clean"})

    def test_hyphenated_subcommand_preserved(self):
        from _dxm_emit import emit_subcommand_complete
        emit_subcommand_complete("handoff", "auto-finalize",
                                  session_id="sub-h")
        events = self._read_events("sub-h")
        self.assertEqual(events[0]["evt_type"],
                          "handoff.auto-finalize.complete")

    def test_intent_tool(self):
        from _dxm_emit import emit_subcommand_complete
        emit_subcommand_complete("intent", "scan",
                                  payload={"matched_count": 3},
                                  session_id="sub-i")
        events = self._read_events("sub-i")
        self.assertEqual(events[0]["evt_type"], "intent.scan.complete")
        self.assertEqual(events[0]["tool_name"], "kaizen-intent")

    def test_payload_optional(self):
        from _dxm_emit import emit_subcommand_complete
        ok = emit_subcommand_complete("handoff", "verify",
                                       session_id="sub-np")
        self.assertTrue(ok)
        events = self._read_events("sub-np")
        self.assertNotIn("payload", events[0])


class TestEventShape(EmitBase):
    def test_record_has_canonical_fields_only(self):
        from _dxm_emit import emit_event
        emit_event("test.shape", session_id="sh", tool_name="kaizen-test",
                    payload={"x": 1})
        events = self._read_events("sh")
        e = events[0]
        # Required fields
        self.assertEqual(set(e.keys()) >= {"ts_unix", "session_id", "evt_type"}, True)
        # Optional fields when supplied
        self.assertIn("tool_name", e)
        self.assertIn("payload", e)

    def test_record_omits_optional_when_absent(self):
        from _dxm_emit import emit_event
        emit_event("test.minimal", session_id="sm")
        events = self._read_events("sm")
        e = events[0]
        self.assertNotIn("tool_name", e)
        self.assertNotIn("payload", e)


if __name__ == "__main__":
    unittest.main()
