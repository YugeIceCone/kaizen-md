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
_HOOK_PY = _KZ_DIR / "scripts/handlers/_write_atomic.py"


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
        target.write_text("OLD")  # pre-create — only overwrites trigger pre-write
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

    def test_overwrite_with_existing_parent_dirs(self):
        target = self.tmp / "deep/nested/out.txt"
        target.parent.mkdir(parents=True)
        target.write_text("OLD")  # pre-create — overwrite path triggers pre-write
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), "x")

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


class TestSkipCreate(unittest.TestCase):
    """For CREATEs (file doesn't exist yet), hook does NOT pre-write —
    avoids CC's 'File has not been read yet' guard on the subsequent
    Write. Atomic only matters for overwrites (partial-write of an
    existing file loses prior data; CREATEs have nothing to lose)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_does_not_pre_write(self):
        target = self.tmp / "fresh.txt"
        self.assertFalse(target.exists())
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "new"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        # File NOT pre-written — hook skipped
        self.assertFalse(target.exists())
        # Context note explains the skip
        self.assertIn("CREATE skipped", ho["additionalContext"])
        # No deny
        self.assertNotIn("permissionDecision", ho)

    def test_overwrite_still_pre_writes(self):
        target = self.tmp / "existing.txt"
        target.write_text("OLD content")
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "NEW content"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        # Pre-write happened
        self.assertEqual(target.read_text(), "NEW content")
        self.assertIn("atomic-write/note", ho["additionalContext"])
        self.assertNotIn("CREATE skipped", ho["additionalContext"])


class TestSkipIdenticalContent(unittest.TestCase):
    """When the intended content equals the current file content, the
    hook is a no-op — no pre-write, no mtime bump. Eliminates spurious
    CC stale-file-guard trips when the agent re-writes its own content
    (e.g. after a tool that internally re-emits the same body)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_identical_content_skips_pre_write(self):
        target = self.tmp / "same.txt"
        target.write_text("UNCHANGED")
        mtime_before = target.stat().st_mtime_ns
        # Sleep to make a stale-write detectable in ns
        import time
        time.sleep(0.01)
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "UNCHANGED"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        # Hook must declare the no-op explicitly so the agent can read intent
        self.assertIn("content-identical", ho["additionalContext"])
        # No deny — let CC's Write run (it will also no-op on identical content)
        self.assertNotIn("permissionDecision", ho)
        # mtime UNCHANGED — the whole point of the short-circuit
        self.assertEqual(target.stat().st_mtime_ns, mtime_before,
                          "hook bumped mtime on identical content — "
                          "stale-file guard will trip on next Write")
        # Content unchanged
        self.assertEqual(target.read_text(), "UNCHANGED")

    def test_different_content_still_pre_writes(self):
        target = self.tmp / "diff.txt"
        target.write_text("BEFORE")
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "AFTER"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        # Different content — pre-write fires normally
        self.assertEqual(target.read_text(), "AFTER")
        self.assertIn("atomic-write/note", ho["additionalContext"])
        self.assertNotIn("content-identical", ho["additionalContext"])


class TestEnforceMode(unittest.TestCase):
    """KAIZEN_ATOMIC_WRITE_MODE=enforce restores the legacy deny-shape:
    pre-write atomically + permissionDecision: deny so CC's Write is
    blocked. Single-writer atomicity at the cost of CC Error-rendering."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_enforce_denies_cc_write(self):
        target = self.tmp / "out.txt"
        target.write_text("OLD")  # pre-create — CREATE-skip would bypass enforce
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        r = _fire_py(evt, env={"KAIZEN_ATOMIC_WRITE_MODE": "enforce"})
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        self.assertEqual(ho["permissionDecision"], "deny")
        self.assertIn("atomic-write/enforce", ho["permissionDecisionReason"])
        # File still written
        self.assertTrue(target.is_file())

    def test_note_mode_is_default_when_unset(self):
        target = self.tmp / "out.txt"
        target.write_text("OLD")  # pre-create — only overwrites trigger pre-write
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        r = _fire_py(evt)  # no MODE set → defaults to "note"
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", ho)
        self.assertIn("atomic-write/note", ho["additionalContext"])

    def test_unknown_mode_falls_back_to_note(self):
        target = self.tmp / "out.txt"
        target.write_text("OLD")  # pre-create
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": str(target), "content": "x"},
        }
        r = _fire_py(evt, env={"KAIZEN_ATOMIC_WRITE_MODE": "wat"})
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", ho)


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
    def test_unwritable_existing_target_falls_through(self):
        # Existing file under /proc that we can't atomically replace.
        # Hook should emit additionalContext explanation, not deny — so
        # CC's Write runs and gets the same OSError surfaced to the agent.
        # /proc/version is a real readable-but-unwritable existing file.
        evt = {
            "tool_name":  "Write",
            "tool_input": {"file_path": "/proc/version",
                            "content": "x"},
        }
        r = _fire_py(evt)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        ho = data.get("hookSpecificOutput", {})
        self.assertNotIn("permissionDecision", ho)
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
        # Pre-create — only overwrites trigger pre-write
        target.write_text("OLD")
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
