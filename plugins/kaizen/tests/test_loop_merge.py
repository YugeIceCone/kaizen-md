"""Unit tests for the ralph-loop merge into kaizen workflow.

Verifies that:
1. setup-ralph-loop.sh writes state to .kaizen/loop.state.md (not .codex/)
2. Both Stop hooks (CC + Codex) read the same state file shape
3. The ralph-loop routine schema parses and registers correctly
4. The /kaizen:loop command file exists and is well-formed

Run:
    python3 -m unittest tests.test_loop_merge -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = PLUGIN_ROOT / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))


SETUP_SCRIPT = PLUGIN_ROOT / "skills" / "loop" / "scripts" / "setup-ralph-loop.sh"
HOOK_CC = PLUGIN_ROOT / "hooks" / "claude" / "stop-ralph.sh"
HOOK_CODEX = PLUGIN_ROOT / "hooks" / "codex" / "stop-ralph.sh"
LOOP_COMMAND = PLUGIN_ROOT / "commands" / "loop.md"
RALPH_SCHEMA = PLUGIN_ROOT / "schemas" / "ralph-loop" / "schema.yaml"
ROUTINES_YAML = PLUGIN_ROOT / "skills" / "workflow" / "domain" / "routines.yaml"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


class TestStatePathMigration(unittest.TestCase):
    """The state-path migration: .codex/ralph-loop.local.md → .kaizen/loop.state.md."""

    def test_setup_script_writes_to_kaizen_state(self):
        self.assertTrue(SETUP_SCRIPT.is_file(), f"setup script missing at {SETUP_SCRIPT}")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            result = subprocess.run(
                ["bash", str(SETUP_SCRIPT), "test prompt", "--max-iterations", "5",
                 "--completion-promise", "DONE"],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(
                (tmp / ".kaizen" / "loop.state.md").is_file(),
                f"expected new state path .kaizen/loop.state.md; setup wrote elsewhere",
            )
            self.assertFalse(
                (tmp / ".codex" / "ralph-loop.local.md").is_file(),
                "legacy .codex/ path should no longer be written",
            )

    def test_setup_state_has_required_frontmatter(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "prompt body", "--max-iterations", "7",
                 "--completion-promise", "FINISHED"],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            self.assertIn("iteration: 1", state)
            self.assertIn("max_iterations: 7", state)
            self.assertIn('completion_promise: "FINISHED"', state)
            # Body after the second `---` is the prompt
            parts = state.split("---")
            self.assertGreaterEqual(len(parts), 3)
            body = parts[2].strip()
            self.assertEqual(body, "prompt body")


class TestStopHooks(unittest.TestCase):
    """Both Stop hooks exist, parse, and respect missing state files."""

    def test_cc_hook_exists_and_executable(self):
        self.assertTrue(HOOK_CC.is_file(), f"CC stop hook missing at {HOOK_CC}")
        self.assertTrue(os.access(HOOK_CC, os.X_OK), "CC stop hook not executable")

    def test_codex_hook_exists_and_executable(self):
        self.assertTrue(HOOK_CODEX.is_file(), f"Codex stop hook missing at {HOOK_CODEX}")
        self.assertTrue(os.access(HOOK_CODEX, os.X_OK), "Codex stop hook not executable")

    def test_hooks_have_valid_bash_syntax(self):
        for hook in (HOOK_CC, HOOK_CODEX):
            result = subprocess.run(
                ["bash", "-n", str(hook)], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, f"{hook}: {result.stderr}")

    def test_hooks_silent_noop_when_no_state(self):
        """Both hooks exit 0 with no JSON when .kaizen/loop.state.md is missing."""
        for hook in (HOOK_CC, HOOK_CODEX):
            with tempfile.TemporaryDirectory() as td:
                result = subprocess.run(
                    ["bash", str(hook)],
                    input=json.dumps({"cwd": td, "session_id": "test", "turn_id": "t1"}),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{hook}: {result.stderr}")
                self.assertEqual(result.stdout.strip(), "")

    def test_hooks_read_new_state_path(self):
        """Both hooks should read .kaizen/loop.state.md, not the legacy path."""
        for hook in (HOOK_CC, HOOK_CODEX):
            with tempfile.TemporaryDirectory() as td:
                # Write a state file at the legacy path — both hooks should ignore it.
                legacy = Path(td) / ".codex" / "ralph-loop.local.md"
                legacy.parent.mkdir(parents=True)
                legacy.write_text("---\nactive: true\niteration: 1\n---\nold")
                result = subprocess.run(
                    ["bash", str(hook)],
                    input=json.dumps({"cwd": td, "session_id": "test"}),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0)
                self.assertEqual(
                    result.stdout.strip(),
                    "",
                    f"{hook}: legacy state file was incorrectly read",
                )

    def test_hooks_emit_block_decision_when_loop_active(self):
        """Both hooks return {decision: 'block', reason: prompt} when state is active."""
        for hook in (HOOK_CC, HOOK_CODEX):
            with tempfile.TemporaryDirectory() as td:
                state_dir = Path(td) / ".kaizen"
                state_dir.mkdir()
                (state_dir / "loop.state.md").write_text(
                    '---\n'
                    'active: true\n'
                    'iteration: 1\n'
                    'session_id: ""\n'  # empty session = match any
                    'last_turn_id: ""\n'
                    'max_iterations: 0\n'
                    'completion_promise: null\n'
                    'started_at: "2026-05-13T00:00:00Z"\n'
                    '---\n'
                    'do the work\n'
                )
                result = subprocess.run(
                    ["bash", str(hook)],
                    input=json.dumps({
                        "cwd": td,
                        "session_id": "any",
                        "turn_id": "t1",
                        "last_assistant_message": "in progress",
                    }),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{hook}: {result.stderr}")
                self.assertNotEqual(result.stdout.strip(), "", f"{hook}: expected JSON output")
                payload = json.loads(result.stdout)
                self.assertEqual(payload["decision"], "block")
                self.assertIn("do the work", payload["reason"])

    def test_hooks_complete_on_promise_match(self):
        """Both hooks stop the loop when last output contains the completion promise."""
        for hook in (HOOK_CC, HOOK_CODEX):
            with tempfile.TemporaryDirectory() as td:
                state_dir = Path(td) / ".kaizen"
                state_dir.mkdir()
                (state_dir / "loop.state.md").write_text(
                    '---\n'
                    'active: true\n'
                    'iteration: 3\n'
                    'session_id: ""\n'
                    'last_turn_id: ""\n'
                    'max_iterations: 10\n'
                    'completion_promise: "DONE"\n'
                    'started_at: "2026-05-13T00:00:00Z"\n'
                    '---\n'
                    'prompt body\n'
                )
                result = subprocess.run(
                    ["bash", str(hook)],
                    input=json.dumps({
                        "cwd": td,
                        "session_id": "any",
                        "turn_id": "t9",
                        "last_assistant_message": "All criteria met. <promise>DONE</promise>",
                    }),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{hook}: {result.stderr}")
                payload = json.loads(result.stdout)
                self.assertEqual(payload["continue"], False)
                self.assertIn("completed", payload["stopReason"].lower())
                # State file removed on completion
                self.assertFalse(
                    (state_dir / "loop.state.md").is_file(),
                    f"{hook}: state file should be removed after promise match",
                )


class TestRoutineRegistration(unittest.TestCase):
    """ralph-loop is registered in routines.yaml and loadable via the workflow loader."""

    def test_schema_file_exists(self):
        self.assertTrue(RALPH_SCHEMA.is_file(), f"schema missing at {RALPH_SCHEMA}")

    def test_routines_yaml_contains_ralph_loop(self):
        text = ROUTINES_YAML.read_text()
        self.assertIn("name: ralph-loop", text)
        self.assertIn("schema_path: schemas/ralph-loop/schema.yaml", text)

    def test_loader_finds_ralph_loop_routine(self):
        sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "application"))
        if "_loader" in sys.modules:
            del sys.modules["_loader"]
        import _loader  # noqa: E402
        # _loader.load_routines() returns a dict keyed by routine name.
        data = _loader.load_routines()
        self.assertIn("ralph-loop", data)
        entry = data["ralph-loop"]
        self.assertEqual(entry["kind"], "schema")
        self.assertEqual(entry["stages"], ["start", "iterate", "verify"])


class TestCommandWiring(unittest.TestCase):
    """The /kaizen:loop command file exists and follows the expected shape."""

    def test_loop_command_exists(self):
        self.assertTrue(LOOP_COMMAND.is_file(), f"missing {LOOP_COMMAND}")

    def test_loop_command_references_new_state_path(self):
        text = LOOP_COMMAND.read_text()
        self.assertIn(".kaizen/loop.state.md", text)
        self.assertNotIn(".codex/ralph-loop.local.md", text)

    def test_loop_command_has_frontmatter(self):
        text = LOOP_COMMAND.read_text()
        self.assertTrue(text.startswith("---\n"), "loop.md must have frontmatter")
        self.assertIn("description:", text)
        self.assertIn("argument-hint:", text)


class TestHooksJson(unittest.TestCase):
    """hooks/hooks.json wires the CC Stop hook for ralph-loop."""

    def test_hooks_json_valid(self):
        data = json.loads(HOOKS_JSON.read_text())
        self.assertIn("hooks", data)
        self.assertIn("Stop", data["hooks"])

    def test_stop_ralph_hook_registered_first(self):
        data = json.loads(HOOKS_JSON.read_text())
        stop_entries = data["hooks"]["Stop"]
        self.assertGreaterEqual(len(stop_entries), 1)
        commands = [
            h["command"]
            for group in stop_entries
            for h in group.get("hooks", [])
        ]
        # stop-ralph.sh must precede stop-backlog-reminder.sh so the loop
        # gets a chance to block before the reminder fires (which would
        # otherwise be a wasted iteration).
        ralph_idx = next(
            (i for i, c in enumerate(commands) if "stop-ralph.sh" in c), -1
        )
        reminder_idx = next(
            (i for i, c in enumerate(commands) if "stop-backlog-reminder.sh" in c), -1
        )
        self.assertGreaterEqual(ralph_idx, 0, "stop-ralph.sh not wired in hooks.json")
        self.assertGreaterEqual(reminder_idx, 0, "stop-backlog-reminder.sh missing")
        self.assertLess(ralph_idx, reminder_idx, "stop-ralph.sh should fire first")


class TestLegacyCleanup(unittest.TestCase):
    """The legacy .codex path is removed from active code paths."""

    def test_legacy_path_absent_from_setup(self):
        text = SETUP_SCRIPT.read_text()
        self.assertNotIn(".codex/ralph-loop.local.md", text)

    def test_legacy_path_absent_from_cancel_cmd(self):
        cancel = PLUGIN_ROOT / "skills" / "loop" / "commands" / "cancel-ralph.md"
        text = cancel.read_text()
        self.assertNotIn(".codex/ralph-loop.local.md", text)
        self.assertIn(".kaizen/loop.state.md", text)


if __name__ == "__main__":
    unittest.main()
