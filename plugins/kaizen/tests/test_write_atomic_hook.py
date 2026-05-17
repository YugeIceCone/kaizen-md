"""Tests for pretooluse-write-atomic — wraps CC Write through _atomic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK_SH = _KZ_DIR / "hooks/claude/pretooluse-write-atomic.sh"
_HOOK_PY = _KZ_DIR / "hooks/claude/_write_atomic.py"


def _fire_py(event: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the backing Python directly with the event on stdin.
    Default env enables the hook (it's opt-in by design). Tests that
    explicitly check opt-OUT semantics can override via env arg."""
    base_env = {"KAIZEN_ATOMIC_WRITE_ENABLE": "1"}
    return subprocess.run(
        [sys.executable, str(_HOOK_PY)],
        input=json.dumps(event), capture_output=True, text=True,
        timeout=5, env={**os.environ, **base_env, **(env or {})},
    )


class TestArtifactsPresent(unittest.TestCase):
    def test_hook_script_present_and_executable(self):
        self.assertTrue(_HOOK_SH.is_file())
        self.assertTrue(os.access(_HOOK_SH, os.X_OK))

    def test_backing_python_present(self):
        self.assertTrue(_HOOK_PY.is_file())
        with open(_HOOK_PY, "r") as f:
            compile(f.read(), str(_HOOK_PY), "exec")


class TestInterception(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_event_atomic_writes_and_notes(self):
        target = self.tmp / "out.txt"
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "hello\n"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        # File on disk with the content (atomic-pre-write happened)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), "hello\n")
        # NEW SHAPE: additionalContext note, NO permissionDecision deny
        ho = data["hookSpecificOutput"]
        self.assertEqual(ho["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", ho,
                          "hook must NOT deny — that renders as Error in CC")
        self.assertIn("atomic-write", ho["additionalContext"])
        self.assertIn("DISABLE", ho["additionalContext"])

    def test_creates_parent_dirs(self):
        target = self.tmp / "deep/nested/out.txt"
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(target.is_file())

    def test_non_write_tool_emits_empty(self):
        evt = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")

    def test_malformed_event_emits_empty(self):
        r = subprocess.run(
            [sys.executable, str(_HOOK_PY)],
            input="not-json", capture_output=True, text=True, timeout=5,
            env={**os.environ, "KAIZEN_ATOMIC_WRITE_ENABLE": "1"},
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")

    def test_missing_fields_emit_empty(self):
        evt = {"tool_name": "Write", "tool_input": {}}
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")


class TestOptInDefault(unittest.TestCase):
    """Hook is opt-IN — without KAIZEN_ATOMIC_WRITE_ENABLE=1 it
    returns empty {} so CC's native Write runs normally + no
    deny-rendered-as-error noise."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_enable_env_short_circuits(self):
        target = self.tmp / "out.txt"
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        # Build env WITHOUT ENABLE; mirror raw os.environ (no opt-in)
        env = {k: v for k, v in os.environ.items()
               if k != "KAIZEN_ATOMIC_WRITE_ENABLE"}
        r = subprocess.run(
            [sys.executable, str(_HOOK_PY)],
            input=json.dumps(evt), capture_output=True, text=True,
            timeout=5, env=env,
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")
        # File NOT written — hook didn't run
        self.assertFalse(target.exists())


class TestBypassKnob(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_disable_env_short_circuits(self):
        target = self.tmp / "out.txt"
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        r = _fire_py(evt, env={"KAIZEN_ATOMIC_WRITE_DISABLE": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")
        # File NOT written (we yielded to CC's Write, which didn't run here)
        self.assertFalse(target.exists())


class TestFallbackOnIOError(unittest.TestCase):
    def test_unwritable_target_falls_through(self):
        # Use an obviously-unwritable path; the hook should emit an
        # additionalContext explanation, not a deny — so CC's Write runs
        # and gets the same OSError surfaced to the agent.
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": "/proc/cannot-write-here.txt",
                            "content": "x"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data.get("hookSpecificOutput", {})
        # No deny (so CC's Write still runs as the fallback)
        self.assertNotIn("permissionDecision", ho)
        # And we surfaced *why* via additionalContext
        self.assertIn("failed",
                       ho.get("additionalContext", ""))


class TestHookScriptIntegration(unittest.TestCase):
    """End-to-end: invoke the bash hook (not just the backing python)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_bash_hook_routes_to_python(self):
        target = self.tmp / "out.txt"
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "via-bash"},
        }
        r = subprocess.run(
            ["bash", str(_HOOK_SH)],
            input=json.dumps(evt), capture_output=True, text=True, timeout=5,
            env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_KZ_DIR),
                  "KAIZEN_ATOMIC_WRITE_ENABLE": "1"},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # Parse the LAST JSON object emitted (the python decision —
        # _trace.sh may emit other stuff first).
        last_json = r.stdout.strip().splitlines()[-1]
        data = json.loads(last_json)
        # NEW SHAPE: additionalContext note, no deny
        ho = data["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", ho)
        self.assertIn("atomic-write", ho.get("additionalContext", ""))
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), "via-bash")


if __name__ == "__main__":
    unittest.main()
