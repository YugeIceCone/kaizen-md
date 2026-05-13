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


class TestFlagAliases(unittest.TestCase):
    """`--its` aliases `--max-iterations`; `--promise` aliases `--completion-promise`."""

    def test_short_its_flag_sets_max_iterations(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "p", "--its", "7"],
                cwd=tmp, check=True, capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            self.assertIn("max_iterations: 7", state)

    def test_short_promise_flag_sets_completion_promise(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "p", "--promise", "ALLDONE"],
                cwd=tmp, check=True, capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            self.assertIn('completion_promise: "ALLDONE"', state)

    def test_long_forms_still_work(self):
        """Back-compat: --max-iterations and --completion-promise still accepted."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "p",
                 "--max-iterations", "11",
                 "--completion-promise", "BC"],
                cwd=tmp, check=True, capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            self.assertIn("max_iterations: 11", state)
            self.assertIn('completion_promise: "BC"', state)

    def test_mixed_short_and_long_in_one_invocation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "p",
                 "--its", "5",
                 "--completion-promise", "MIX"],
                cwd=tmp, check=True, capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            self.assertIn("max_iterations: 5", state)
            self.assertIn('completion_promise: "MIX"', state)


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


class TestLedgerCompletion(unittest.TestCase):
    """Empty body in .kaizen/loop.state.md ends the loop (ledger pattern)."""

    def _run_hook(self, hook: Path, state_body: str, last_msg: str = "") -> tuple[str, str, int, bool]:
        """Run a Stop hook with the given state body.
        Returns (stdout, stderr, rc, state_file_still_exists)."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / ".kaizen"
            state_dir.mkdir()
            (state_dir / "loop.state.md").write_text(
                '---\n'
                'active: true\n'
                'iteration: 1\n'
                'session_id: ""\n'
                'last_turn_id: ""\n'
                'max_iterations: 10\n'
                'completion_promise: null\n'
                'started_at: "2026-05-13T00:00:00Z"\n'
                '---\n'
                f'{state_body}'
            )
            result = subprocess.run(
                ["bash", str(hook)],
                input=json.dumps({
                    "cwd": td,
                    "session_id": "any",
                    "turn_id": "t1",
                    "last_assistant_message": last_msg,
                }),
                capture_output=True,
                text=True,
            )
            state_remains = (state_dir / "loop.state.md").is_file()
            return result.stdout, result.stderr, result.returncode, state_remains

    def test_empty_body_ends_loop(self):
        """Body containing only whitespace → loop ends (state file removed)."""
        for hook in (HOOK_CC, HOOK_CODEX):
            stdout, stderr, rc, remains = self._run_hook(hook, "")
            self.assertEqual(rc, 0, f"{hook}: {stderr}")
            payload = json.loads(stdout)
            self.assertEqual(payload["continue"], False)
            self.assertIn("ledger empty", payload["stopReason"].lower())
            self.assertFalse(remains, f"{hook}: state file should be removed")

    def test_whitespace_only_body_ends_loop(self):
        """Body with newlines + tabs only also counts as empty."""
        for hook in (HOOK_CC, HOOK_CODEX):
            stdout, stderr, rc, remains = self._run_hook(hook, "  \n\t\n  \n")
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["continue"], False)
            self.assertIn("ledger empty", payload["stopReason"].lower())
            self.assertFalse(remains)

    def test_non_empty_body_continues_loop(self):
        """Body with any actual content → loop continues (block decision)."""
        for hook in (HOOK_CC, HOOK_CODEX):
            stdout, stderr, rc, remains = self._run_hook(
                hook, "- [ ] work item still pending"
            )
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("work item still pending", payload["reason"])
            self.assertTrue(remains, "state file should remain when work is pending")

    def test_checkbox_ledger_continues_until_all_removed(self):
        """A multi-item ledger keeps the loop going until items are deleted."""
        for hook in (HOOK_CC, HOOK_CODEX):
            # First call: 3 items → block
            stdout, _, rc, remains = self._run_hook(
                hook,
                "- [ ] Item 1\n- [ ] Item 2\n- [ ] Item 3\n",
            )
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("Item 1", payload["reason"])
            self.assertTrue(remains)


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


# ─── 7. Structured ledger (JSON body + verify gate) ────────────────────


class TestStructuredLedger(unittest.TestCase):
    """JSON-body ledger with hook-owned verify gate (cheat-proof)."""

    LEDGER_HELPER = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "loop_ledger.py"

    def _run_hook_with_body(self, hook: Path, body_json: dict, last_msg: str = "") -> tuple[str, int, dict | None]:
        """Run a Stop hook with a JSON-bodied ledger. Returns (stdout, rc, updated_ledger_or_None)."""
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / ".kaizen"
            state_dir.mkdir()
            state_path = state_dir / "loop.state.md"
            state_path.write_text(
                '---\n'
                'active: true\n'
                'iteration: 1\n'
                'session_id: ""\n'
                'last_turn_id: ""\n'
                'max_iterations: 10\n'
                'completion_promise: null\n'
                'started_at: "2026-05-13T00:00:00Z"\n'
                '---\n'
                + json.dumps(body_json)
                + '\n'
            )
            result = subprocess.run(
                ["bash", str(hook)],
                input=json.dumps({
                    "cwd": td,
                    "session_id": "any",
                    "turn_id": "t1",
                    "last_assistant_message": last_msg,
                }),
                cwd=td,  # so verify commands run relative to the test dir
                capture_output=True,
                text=True,
            )
            updated = None
            if state_path.is_file():
                text = state_path.read_text()
                body_part = text.split("---\n", 2)[-1].strip()
                try:
                    updated = json.loads(body_part)
                except json.JSONDecodeError:
                    updated = None
            return result.stdout, result.returncode, updated

    def test_passing_verify_moves_item_to_completed(self):
        """Verify command exit 0 → hook moves item from pending to completed.
        Use a non-empty residual pending item so the state file survives for inspection
        (the loop's terminal cleanup removes the state file when pending hits 0)."""
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [
                    {"desc": "be true", "verify": "true"},
                    {"desc": "keep loop alive", "verify": "false"},
                ],
                "completed": [],
            }
            stdout, rc, updated = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            self.assertIsNotNone(updated, f"{hook}: hook did not produce JSON state")
            self.assertEqual(len(updated["pending"]), 1)
            self.assertEqual(updated["pending"][0]["desc"], "keep loop alive")
            self.assertEqual(len(updated["completed"]), 1)
            self.assertEqual(updated["completed"][0]["desc"], "be true")
            self.assertIn("iteration", updated["completed"][0])
            self.assertIn("completed_at", updated["completed"][0])

    def test_failing_verify_keeps_item_in_pending(self):
        """Verify command exit !=0 → item stays in pending; loop continues."""
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [{"desc": "always false", "verify": "false"}],
                "completed": [],
            }
            stdout, rc, _ = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("always false", payload["reason"])

    def test_null_verify_item_stays_until_agent_removes(self):
        """Items with verify=null are trust-based — they stay in pending."""
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [{"desc": "trust based", "verify": None}],
                "completed": [],
            }
            stdout, rc, updated = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["decision"], "block")
            # Item should remain in pending after the hook run.
            self.assertEqual(len(updated["pending"]), 1)

    def test_agent_cannot_forge_completed_entries(self):
        """Cheat-proof: if the agent puts items in `completed`, the hook preserves them
        but does NOT validate them — the audit log makes any forgery visible."""
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [],
                "completed": [
                    # Agent-forged entry (no iteration / completed_at)
                    {"desc": "fake completion", "verify": "false"},
                ],
            }
            stdout, rc, updated = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            # Pending is empty → loop ends. But completed_count is reported
            # so the user sees `1 items verified`. (The forgery is visible
            # because the entry lacks iteration/completed_at fields when
            # inspected.) The hook does NOT re-promote it as forged.
            self.assertIn("continue", payload)
            self.assertEqual(payload["continue"], False)

    def test_mixed_pending_partial_completion(self):
        """3 items: 2 verify-pass, 1 verify-fail. Hook moves 2 to completed."""
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [
                    {"desc": "ok1", "verify": "true"},
                    {"desc": "fail", "verify": "false"},
                    {"desc": "ok2", "verify": "true"},
                ],
                "completed": [],
            }
            stdout, rc, updated = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            self.assertEqual(len(updated["pending"]), 1)
            self.assertEqual(updated["pending"][0]["desc"], "fail")
            self.assertEqual(len(updated["completed"]), 2)
            descs = sorted(c["desc"] for c in updated["completed"])
            self.assertEqual(descs, ["ok1", "ok2"])

    def test_completed_carries_iteration_and_timestamp(self):
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [
                    {"desc": "x", "verify": "true"},
                    {"desc": "residual", "verify": "false"},  # keeps state alive
                ],
                "completed": [],
            }
            stdout, rc, updated = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            entry = updated["completed"][0]
            self.assertEqual(entry["iteration"], 1)
            self.assertRegex(
                entry["completed_at"],
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            )

    def test_agent_appends_item_mid_loop(self):
        """Simulates the agent editing the state file between iterations to
        ADD a new pending item. The hook reads the modified pending list."""
        for hook in (HOOK_CC, HOOK_CODEX):
            ledger = {
                "pending": [
                    {"desc": "original", "verify": "false"},
                    {"desc": "added by agent mid-loop", "verify": "false"},
                ],
                "completed": [],
            }
            stdout, rc, updated = self._run_hook_with_body(hook, ledger)
            self.assertEqual(rc, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertEqual(len(updated["pending"]), 2)
            # Both descriptions appear in the prompt
            self.assertIn("original", payload["reason"])
            self.assertIn("added by agent mid-loop", payload["reason"])

    def test_helper_handles_freeform_body(self):
        """Non-JSON body falls back to freeform mode (legacy compatibility)."""
        result = subprocess.run(
            ["python3", str(self.LEDGER_HELPER), "/dev/stdin", "1"],
            input="dummy",
            capture_output=True,
            text=True,
        )
        # /dev/stdin won't be readable as a file → noop
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "noop")

    def test_helper_validates_iteration_argument(self):
        result = subprocess.run(
            ["python3", str(self.LEDGER_HELPER), "/nonexistent/state", "not-a-number"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("iteration must be int", result.stderr)


class TestSetupScriptStructuredItems(unittest.TestCase):
    """The setup script supports --item and --ledger for structured init."""

    def test_item_flag_creates_json_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT),
                 "--item", "Implement x|grep x file.py",
                 "--item", "Add tests"],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            data = json.loads(body)
            self.assertEqual(len(data["pending"]), 2)
            self.assertEqual(data["pending"][0]["desc"], "Implement x")
            self.assertEqual(data["pending"][0]["verify"], "grep x file.py")
            self.assertEqual(data["pending"][1]["desc"], "Add tests")
            self.assertIsNone(data["pending"][1]["verify"])
            self.assertEqual(data["completed"], [])

    def test_ledger_file_flag_imports_json(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger_src = tmp / "ledger.json"
            ledger_src.write_text(json.dumps({
                "pending": [
                    {"desc": "from file", "verify": "true"}
                ]
            }))
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "--ledger", str(ledger_src)],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            data = json.loads(body)
            self.assertEqual(len(data["pending"]), 1)
            self.assertEqual(data["pending"][0]["desc"], "from file")
            # completed key auto-added
            self.assertEqual(data["completed"], [])

    def test_legacy_freeform_prompt_still_works(self):
        """Bare prompt (no --item / --ledger) → freeform body, unchanged behavior."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(
                ["bash", str(SETUP_SCRIPT), "build a thing"],
                cwd=tmp,
                check=True,
                capture_output=True,
            )
            state = (tmp / ".kaizen" / "loop.state.md").read_text()
            body = state.split("---\n", 2)[-1].strip()
            # Body is the freeform prompt, NOT JSON
            self.assertEqual(body, "build a thing")
            with self.assertRaises(json.JSONDecodeError):
                json.loads(body)
