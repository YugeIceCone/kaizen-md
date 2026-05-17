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


class TestStripNoncommand(unittest.TestCase):
    """_strip_noncommand() — heredoc bodies + quoted literals are DATA."""

    def test_strips_heredoc_body(self):
        cmd = ("git commit -m \"$(cat <<'EOF'\n"
               "fix the git push --force regression\n"
               "EOF\n"
               ")\"")
        stripped = _bash_gate._strip_noncommand(cmd)
        self.assertNotIn("git push --force", stripped)

    def test_strips_double_quoted_string(self):
        stripped = _bash_gate._strip_noncommand('git commit -m "rm -rf bug"')
        self.assertNotIn("rm -rf", stripped)

    def test_strips_single_quoted_string(self):
        stripped = _bash_gate._strip_noncommand("echo 'git reset --hard'")
        self.assertNotIn("git reset --hard", stripped)

    def test_keeps_unquoted_command_tokens(self):
        stripped = _bash_gate._strip_noncommand("rm -rf /home/user/project")
        self.assertIn("rm -rf /home/user/project", stripped)


class TestQuotedFalsePositives(unittest.TestCase):
    """decide() must not gate on destructive ops quoted inside DATA.

    Regression: a `git commit` whose heredoc message mentioned
    `git push --force` was flagged as a force-push and forced a prompt.
    """

    def test_commit_heredoc_mentioning_force_push_is_clean(self):
        cmd = ("cd ~/repo && git commit -m \"$(cat <<'EOF'\n"
               "perf(hooks): collapse the gate\n"
               "The --force regex never matched git push --force-with-lease.\n"
               "EOF\n"
               ")\" 2>&1 | tail -10")
        self.assertEqual(_bash_gate.decide(cmd), {})

    def test_commit_dash_m_mentioning_rm_rf_is_clean(self):
        self.assertEqual(_bash_gate.decide('git commit -m "fix rm -rf /foo bug"'), {})

    def test_echo_of_destructive_string_is_clean(self):
        self.assertEqual(_bash_gate.decide("echo 'git reset --hard HEAD'"), {})

    def test_real_force_push_still_gated(self):
        out = _bash_gate.decide("git push --force origin main")
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_real_rm_rf_still_gated_with_quoted_path(self):
        # The `rm -rf` prefix is unquoted; only the path is quoted. Stripping
        # the path leaves `rm -rf ` — still flagged (and the safe-path check
        # can't see /tmp, so it errs toward asking; acceptable).
        out = _bash_gate.decide('rm -rf "/home/user/important dir"')
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_real_destructive_after_heredoc_still_gated(self):
        cmd = ("cat <<'EOF'\njust some text\nEOF\n"
               "git push --force")
        out = _bash_gate.decide(cmd)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "ask")


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


class TestEtuDecision(unittest.TestCase):
    """etu_decision blocks on error-severity anti-patterns surfaced by
    skills/efficient-tool-use/application/etu_scan.scan_text."""

    def test_eval_user_input_blocks(self):
        r = _bash_gate.decide('eval "$user_input"')
        self.assertEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask"
        )
        self.assertIn("eval", r["hookSpecificOutput"]["permissionDecisionReason"])

    def test_find_from_root_blocks(self):
        r = _bash_gate.decide("find / -name foo")
        self.assertEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask"
        )

    def test_warn_severity_not_blocked(self):
        # grep | wc -l is INFO-severity — not an `ask` decision
        r = _bash_gate.decide("grep X file | wc -l")
        self.assertNotEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask"
        )

    def test_disable_env_var_short_circuits_etu(self):
        import os
        os.environ["KAIZEN_ETU_GATE_DISABLE"] = "1"
        try:
            r = _bash_gate.decide('eval "$x"')
            # Without etu, eval doesn't trigger destructive-op decision either
            self.assertNotEqual(
                r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask"
            )
        finally:
            del os.environ["KAIZEN_ETU_GATE_DISABLE"]

    def test_grep_for_eval_string_is_not_blocked(self):
        # Literal "eval " inside a quoted grep argument is data, not a shell
        # builtin invocation — the etu gate must not flag it.
        r = _bash_gate.decide('grep -rn "eval " plugins/')
        self.assertNotEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask",
            f"unexpected ask: {r}"
        )

    def test_grep_for_eval_inside_single_quotes_is_not_blocked(self):
        r = _bash_gate.decide("grep -n 'eval \\\"$x\\\"' plugins/")
        self.assertNotEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask",
            f"unexpected ask: {r}"
        )

    def test_eval_after_separator_still_blocks(self):
        # Real eval after a command separator must still be caught.
        r = _bash_gate.decide('ls; eval "$x"')
        self.assertEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask"
        )


class TestAfkMode(unittest.TestCase):
    """AFK mode (env KAIZEN_AFK_MODE=1 or sentinel ~/.claude/.kaizen/afk)
    downgrades every `ask` decision to `allow + systemMessage` so an
    unattended Claude session keeps making progress."""

    def setUp(self):
        import os
        self._orig_afk = os.environ.pop("KAIZEN_AFK_MODE", None)
        # Point sentinel at a tmp file we control — avoids reading the
        # real user-global sentinel during tests.
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(delete=False)
        self._tmp.close()
        # Don't actually exist by default — tests opt in by writing.
        Path(self._tmp.name).unlink(missing_ok=True)
        os.environ["KAIZEN_AFK_FILE"] = self._tmp.name

    def tearDown(self):
        import os
        Path(self._tmp.name).unlink(missing_ok=True)
        os.environ.pop("KAIZEN_AFK_FILE", None)
        if self._orig_afk is not None:
            os.environ["KAIZEN_AFK_MODE"] = self._orig_afk

    def test_afk_inactive_eval_still_asks(self):
        r = _bash_gate.decide('eval "$x"')
        self.assertEqual(
            r.get("hookSpecificOutput", {}).get("permissionDecision"), "ask"
        )

    def test_afk_via_env_var_downgrades_eval_to_advisory(self):
        import os
        os.environ["KAIZEN_AFK_MODE"] = "1"
        try:
            r = _bash_gate.decide('eval "$x"')
        finally:
            os.environ.pop("KAIZEN_AFK_MODE", None)
        self.assertNotIn("hookSpecificOutput", r)
        self.assertIn("systemMessage", r)
        self.assertIn("AFK", r["systemMessage"])
        self.assertIn("eval", r["systemMessage"])

    def test_afk_via_sentinel_downgrades_force_push_to_advisory(self):
        Path(self._tmp.name).touch()
        r = _bash_gate.decide('git push --force origin master')
        self.assertNotIn("hookSpecificOutput", r)
        self.assertIn("systemMessage", r)
        self.assertIn("AFK", r["systemMessage"])
        self.assertIn("force", r["systemMessage"])

    def test_afk_does_not_swallow_advisory_only_findings(self):
        # A discipline-warn command (no ask) under AFK is unchanged.
        Path(self._tmp.name).touch()
        r = _bash_gate.decide("grep X file | wc -l")
        # Either clean or systemMessage — never ask.
        self.assertNotIn("hookSpecificOutput", r)


class TestLongFormNudge(unittest.TestCase):
    """long_form_nudge advises (systemMessage) when kaizen scripts are
    invoked via long paths instead of `kaizen <sub>`."""

    def test_bin_long_form_caught(self):
        cmd = "bash plugins/kaizen/bin/kaizen-gatekeeper check --staged"
        r = _bash_gate.decide(cmd)
        self.assertIn("kaizen-cli nudge", r.get("systemMessage", ""))
        self.assertIn("kaizen gatekeeper", r["systemMessage"])

    def test_script_long_form_caught(self):
        cmd = "python3 plugins/kaizen/skills/workflow/scripts/gatekeeper.py check --all"
        r = _bash_gate.decide(cmd)
        self.assertIn("kaizen-cli nudge", r.get("systemMessage", ""))
        self.assertIn("kaizen gatekeeper", r["systemMessage"])

    def test_mcp_module_not_nudged(self):
        # *_mcp.py modules aren't aliased — they're for the MCP gateway,
        # not direct CLI invocation.
        cmd = "uv run --script plugins/kaizen/skills/workflow/scripts/gatekeeper_mcp.py"
        r = _bash_gate.decide(cmd)
        self.assertNotIn("kaizen-cli nudge", r.get("systemMessage", ""))

    def test_clean_command_no_nudge(self):
        r = _bash_gate.decide("ls -la")
        self.assertEqual(r, {})

    def test_nudge_combines_cleanly(self):
        cmd = "bash plugins/kaizen/bin/kaizen-audit"
        r = _bash_gate.decide(cmd)
        self.assertIn("kaizen-cli nudge", r.get("systemMessage", ""))
        self.assertIn("kaizen audit", r["systemMessage"])


if __name__ == "__main__":
    unittest.main()
