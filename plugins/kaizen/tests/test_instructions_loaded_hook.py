"""Tests for hooks/claude/instructions-loaded-trace.sh.

Observability-only hook: fires on every CLAUDE.md / rules load,
composes _trace.sh, and atomic-appends a JSONL audit line.

Sandbox: KAIZEN_INSTRUCTIONS_LOADED_LOG points the log file at a
tempfile (matches the per-feature env convention).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HOOK = ROOT / "hooks/claude/instructions-loaded-trace.sh"


def _run_hook(payload: dict, env_extra: dict | None = None):
    env = os.environ.copy()
    # Silence the trace composition so tests don't fan out beyond the log.
    env["KAIZEN_TRACE_DISABLE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5, env=env,
    )


class TestHookSmoke(unittest.TestCase):

    def test_hook_script_is_present_and_executable(self):
        self.assertTrue(_HOOK.is_file(), f"missing: {_HOOK}")
        self.assertTrue(os.access(_HOOK, os.X_OK),
                         "hook must be chmod +x for the harness to invoke it")

    def test_hook_exits_zero_on_empty_input(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "loaded.jsonl"
            r = subprocess.run(
                ["bash", str(_HOOK)],
                input="", capture_output=True, text=True, timeout=5,
                env={**os.environ,
                     "KAIZEN_TRACE_DISABLE": "1",
                     "KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log)},
            )
        # Observability hook MUST never block — always exits 0.
        self.assertEqual(r.returncode, 0)


class TestJsonlAppend(unittest.TestCase):

    def test_appends_one_line_per_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "loaded.jsonl"
            payload = {
                "session_id": "abc",
                "hook_event_name": "InstructionsLoaded",
                "file_path": "/u/x/CLAUDE.md",
                "memory_type": "User",
                "load_reason": "session_start",
            }
            _run_hook(payload, {"KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log)})
            _run_hook(payload, {"KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log)})
            text = log.read_text()
            lines = [l for l in text.splitlines() if l.strip()]
            self.assertEqual(len(lines), 2)
            for line in lines:
                entry = json.loads(line)
                self.assertEqual(entry["file_path"], "/u/x/CLAUDE.md")
                self.assertEqual(entry["memory_type"], "User")
                self.assertEqual(entry["load_reason"], "session_start")
                self.assertIn("ts", entry)

    def test_preserves_optional_fields_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "loaded.jsonl"
            payload = {
                "session_id": "abc",
                "hook_event_name": "InstructionsLoaded",
                "file_path": "/u/x/.claude/rules/api.md",
                "memory_type": "Project",
                "load_reason": "path_glob_match",
                "globs": ["src/api/**/*.ts"],
                "trigger_file_path": "/u/x/src/api/foo.ts",
            }
            _run_hook(payload, {"KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log)})
            entry = json.loads(log.read_text().strip())
            self.assertEqual(entry["globs"], ["src/api/**/*.ts"])
            self.assertEqual(entry["trigger_file_path"],
                             "/u/x/src/api/foo.ts")

    def test_omits_optional_fields_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "loaded.jsonl"
            payload = {
                "session_id": "abc",
                "hook_event_name": "InstructionsLoaded",
                "file_path": "/u/x/CLAUDE.md",
                "memory_type": "User",
                "load_reason": "session_start",
            }
            _run_hook(payload, {"KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log)})
            entry = json.loads(log.read_text().strip())
            self.assertNotIn("globs", entry)
            self.assertNotIn("trigger_file_path", entry)
            self.assertNotIn("parent_file_path", entry)


class TestDisableEnv(unittest.TestCase):

    def test_disable_env_suppresses_write(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "loaded.jsonl"
            payload = {
                "session_id": "abc",
                "hook_event_name": "InstructionsLoaded",
                "file_path": "/u/x/CLAUDE.md",
                "memory_type": "User",
                "load_reason": "session_start",
            }
            _run_hook(payload, {
                "KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log),
                "KAIZEN_INSTRUCTIONS_LOADED_DISABLE": "1",
            })
            self.assertFalse(log.exists(),
                             "disable env must skip the jsonl write entirely")


class TestNeverBlocks(unittest.TestCase):

    def test_malformed_json_input_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "loaded.jsonl"
            r = subprocess.run(
                ["bash", str(_HOOK)],
                input="this is not JSON {{{",
                capture_output=True, text=True, timeout=5,
                env={**os.environ,
                     "KAIZEN_TRACE_DISABLE": "1",
                     "KAIZEN_INSTRUCTIONS_LOADED_LOG": str(log)},
            )
        # Hook is non-blocking — bad input must not break the session.
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
