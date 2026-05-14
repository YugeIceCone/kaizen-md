"""Tests for hooks/claude/_bash_gate.py — the unified PreToolUse Bash gate.

_bash_gate.py collapses the old multi-python3 pretooluse-bash-gate.sh into
one process: command extraction + destructive-op match + bash-discipline
scan + decision emit. These tests cover the pure decision surface plus the
stdin event parse.

Run:
    python3 -m unittest tests.test_bash_gate -v
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest import mock

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks" / "claude"

import sys
sys.path.insert(0, str(HOOKS_DIR))
import _bash_gate  # noqa: E402


class TestDestructiveDecision(unittest.TestCase):
    """destructive_decision() — the ask-gate for risky commands."""

    def test_clean_command_is_none(self):
        self.assertIsNone(_bash_gate.destructive_decision("ls -la"))
        self.assertIsNone(_bash_gate.destructive_decision("git status"))

    def test_git_push_force_asks(self):
        d = _bash_gate.destructive_decision("git push --force origin main")
        self.assertIsNotNone(d)
        self.assertEqual(d[0], "ask")
        self.assertIn("remote history", d[1])

    def test_git_push_force_with_lease_asks(self):
        d = _bash_gate.destructive_decision("git push --force-with-lease")
        self.assertIsNotNone(d)
        self.assertEqual(d[0], "ask")

    def test_git_reset_hard_asks(self):
        d = _bash_gate.destructive_decision("git reset --hard HEAD~1")
        self.assertIsNotNone(d)
        self.assertEqual(d[0], "ask")
        self.assertIn("uncommitted", d[1])

    def test_git_clean_asks(self):
        d = _bash_gate.destructive_decision("git clean -fd")
        self.assertIsNotNone(d)
        self.assertEqual(d[0], "ask")

    def test_rm_rf_outside_tmp_asks(self):
        d = _bash_gate.destructive_decision("rm -rf /home/user/project")
        self.assertIsNotNone(d)
        self.assertEqual(d[0], "ask")
        self.assertIn("source-of-truth", d[1])

    def test_rm_rf_under_tmp_is_allowed(self):
        self.assertIsNone(_bash_gate.destructive_decision("rm -rf /tmp/scratch"))
        self.assertIsNone(_bash_gate.destructive_decision("rm -rf /var/tmp/x"))

    def test_git_rm_asks_when_belief_present(self):
        # Point the belief path at a file that exists (this test file).
        with mock.patch.object(_bash_gate, "_NO_DELETIONS_BELIEF",
                               Path(__file__)):
            d = _bash_gate.destructive_decision("git rm old_file.py")
        self.assertIsNotNone(d)
        self.assertEqual(d[0], "ask")
        self.assertIn("no-deletions belief", d[1])

    def test_git_rm_silent_when_belief_absent(self):
        with mock.patch.object(_bash_gate, "_NO_DELETIONS_BELIEF",
                               Path("/nonexistent/pref-no-deletions.md")):
            self.assertIsNone(_bash_gate.destructive_decision("git rm old_file.py"))

    def test_git_rm_not_matched_as_substring(self):
        # `git rmdir`-style tokens must not trip the git-rm rule.
        with mock.patch.object(_bash_gate, "_NO_DELETIONS_BELIEF",
                               Path(__file__)):
            self.assertIsNone(_bash_gate.destructive_decision("echo git rmdir"))


class TestAdvisoryMessage(unittest.TestCase):
    """advisory_message() — reuses scan() from _bash_discipline_scan.py."""

    def test_clean_command_no_advisory(self):
        self.assertIsNone(_bash_gate.advisory_message("ls -la"))

    def test_rm_in_compound_warns(self):
        msg = _bash_gate.advisory_message("rm -rf build && mkdir build")
        self.assertIsNotNone(msg)
        self.assertIn("bash-discipline advisory", msg)
        self.assertIn("rm_in_isolation", msg)


class TestDecide(unittest.TestCase):
    """decide() — the full command-in / hook-output-dict-out surface."""

    def test_empty_command_is_empty_dict(self):
        self.assertEqual(_bash_gate.decide(""), {})

    def test_clean_command_is_empty_dict(self):
        self.assertEqual(_bash_gate.decide("git status"), {})

    def test_destructive_emits_permission_decision(self):
        out = _bash_gate.decide("git push --force")
        self.assertIn("hookSpecificOutput", out)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "ask")

    def test_advisory_emits_system_message(self):
        out = _bash_gate.decide("rm -rf build && mkdir build")
        # rm -rf outside /tmp is destructive — that wins over the advisory.
        self.assertIn("hookSpecificOutput", out)

    def test_advisory_only_when_not_destructive(self):
        # A compound with a non-destructive rm-shaped discipline hit:
        # `cd x && rm file && ls` — rm (not -rf) in a compound triggers
        # the rm_in_isolation advisory but not the destructive gate.
        out = _bash_gate.decide("cd x && rm file.txt && ls")
        self.assertIn("systemMessage", out)
        self.assertIn("bash-discipline advisory", out["systemMessage"])

    def test_destructive_takes_precedence_over_advisory(self):
        out = _bash_gate.decide("git reset --hard && echo done")
        self.assertIn("hookSpecificOutput", out)
        self.assertNotIn("systemMessage", out)


class TestReadCommand(unittest.TestCase):
    """_read_command() — stdin event JSON parse, defensive on every shape."""

    def _run(self, stdin_text: str) -> str:
        with mock.patch.object(_bash_gate.sys, "stdin", io.StringIO(stdin_text)):
            return _bash_gate._read_command()

    def test_valid_event(self):
        evt = json.dumps({"tool_input": {"command": "ls -la"}})
        self.assertEqual(self._run(evt), "ls -la")

    def test_missing_tool_input(self):
        self.assertEqual(self._run('{"session_id": "x"}'), "")

    def test_missing_command(self):
        self.assertEqual(self._run('{"tool_input": {}}'), "")

    def test_malformed_json(self):
        self.assertEqual(self._run("not json at all"), "")

    def test_empty_stdin(self):
        self.assertEqual(self._run(""), "")

    def test_non_dict_json(self):
        self.assertEqual(self._run("[1, 2, 3]"), "")

    def test_null_command(self):
        self.assertEqual(self._run('{"tool_input": {"command": null}}'), "")


class TestModuleParses(unittest.TestCase):
    """The module file compiles — catches syntax errors in deps-free CI."""

    def test_module_script_parses(self):
        path = HOOKS_DIR / "_bash_gate.py"
        with open(path, "r", encoding="utf-8") as f:
            compile(f.read(), str(path), "exec")


if __name__ == "__main__":
    unittest.main()
