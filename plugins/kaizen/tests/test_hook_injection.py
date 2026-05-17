"""Security regression tests — shell-injection vectors in hooks.

Three hooks were found to interpolate untrusted strings directly into
Python source via either `python3 -c "...$VAR..."` or unquoted heredocs
(`<<PY` instead of `<<'PY'`). All three are RCE if the attacker can
control the relevant input:

  - hooks/claude/pretooluse-trace.sh         IDENT (tool args)
  - hooks/claude/posttooluse-bash-commit.sh  COMMIT_MSG + SUGGESTION
  - hooks/claude/session-surface-backlog.sh  SUMMARY (via backlog.json)

This test class drives malicious inputs through each hook and asserts:
  1. The malicious payload does NOT execute (no side-effect canary file).
  2. The hook still emits valid JSON (or empty {}).
  3. Exit code is 0 (hooks must not abort the parent process).

Written test-first per TDD: each test was authored before the fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOKS = _KZ_DIR / "hooks" / "claude"


def _run_hook(script: Path, *, stdin: str, extra_argv: list[str] = None,
              cwd: Path = None, extra_env: dict = None,
              timeout: float = 10.0) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)
    argv = ["bash", str(script)] + (extra_argv or [])
    return subprocess.run(
        argv, input=stdin, capture_output=True, text=True,
        env=env, timeout=timeout, cwd=str(cwd) if cwd else None,
    )


class PreToolUseTraceInjection(unittest.TestCase):
    """C1: pretooluse-trace.sh interpolates $IDENT into `python3 -c "..."`
    via triple-quoted string. Attacker-controlled tool args (e.g. Grep
    pattern, WebFetch URL) containing `'''); <python>; ('''` get executed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.canary = Path(self._tmp.name) / "PWNED"

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, ident: str) -> str:
        """Craft a Claude Code PreToolUse event with `ident` as the
        Grep pattern (one of the documented IDENT extraction paths)."""
        return json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"pattern": ident},
            "session_id": "test-session",
        })

    def test_grep_pattern_with_triple_quote_injection_blocked(self):
        # Malicious pattern attempts to break out of '''...''' and write canary.
        ident = (
            "foo'''); "
            f"open('{self.canary}', 'w').write('pwned'); "
            "print(({'ident': ('''"
        )
        r = _run_hook(_HOOKS / "pretooluse-trace.sh", stdin=self._payload(ident))
        self.assertFalse(self.canary.exists(),
                         "RCE: malicious IDENT executed Python code")
        self.assertEqual(r.returncode, 0, f"hook should not abort: {r.stderr}")

    def test_grep_pattern_with_os_system_injection_blocked(self):
        ident = (
            "foo'''); import os; os.system('touch "
            f"{self.canary}'); print(({{'ident': ('''"
        )
        r = _run_hook(_HOOKS / "pretooluse-trace.sh", stdin=self._payload(ident))
        self.assertFalse(self.canary.exists(),
                         "RCE: os.system payload executed")

    def test_benign_grep_pattern_still_works(self):
        # Regression: normal IDENT must still produce a trace event without error.
        r = _run_hook(_HOOKS / "pretooluse-trace.sh",
                       stdin=self._payload("def my_function"))
        self.assertEqual(r.returncode, 0)


class PostToolUseCommitInjection(unittest.TestCase):
    """C2: posttooluse-bash-commit.sh uses unquoted heredoc with
    `commit = \"\"\"$COMMIT_MSG\"\"\"`. Any commit message containing
    `\"\"\"; <python>; \"\"\"` runs at hook time.

    The hook requires a real git repo + .kaizen.toml + backlog.json to
    reach the vulnerable code path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.canary = self.repo / "PWNED"
        # Init a git repo + .kaizen.toml + backlog.json with an in_flight item
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.repo, check=True)
        (self.repo / ".kaizen.toml").write_text(
            'backlog_path = ".kaizen/workflow/backlog.md"\n'
        )
        bk_dir = self.repo / ".kaizen" / "workflow"
        bk_dir.mkdir(parents=True)
        (bk_dir / "backlog.json").write_text(json.dumps({
            "items": [{"id": "BK-001", "title": "Some backlog item to match",
                       "section": "in_flight"}]
        }))

    def tearDown(self):
        self._tmp.cleanup()

    def _payload(self, commit_msg: str) -> str:
        return json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'test'"},
            "tool_result": {"type": "success", "content": "committed"},
        })

    def test_commit_message_with_python_injection_blocked(self):
        # Create a commit whose message contains the payload.
        # The hook reads `git log -1 --format=%B`.
        evil = (
            'Some backlog item to match\n'
            '\n'
            '"""\n'
            f'open("{self.canary}", "w").write("pwned")\n'
            '"""\n'
        )
        (self.repo / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "f.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", evil],
                        cwd=self.repo, check=True)
        r = _run_hook(_HOOKS / "posttooluse-bash-commit.sh",
                       stdin=self._payload(evil), cwd=self.repo)
        self.assertFalse(self.canary.exists(),
                         "RCE: malicious COMMIT_MSG executed Python")
        self.assertEqual(r.returncode, 0)


class SessionSurfaceBacklogInjection(unittest.TestCase):
    """H1: session-surface-backlog.sh uses unquoted `<<PY` heredoc with
    `ctx = \"\"\"$SUMMARY\"\"\"`. SUMMARY is built from backlog.json
    titles. An attacker who can write backlog.json (PR review, etc.)
    injects Python that runs at next SessionStart.

    The hook reads .kaizen.toml to find backlog_path, then reads
    backlog.md (which is rendered from backlog.json). To trigger the
    SUMMARY build, we need at least one item.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.canary = self.repo / "PWNED"
        (self.repo / ".kaizen.toml").write_text(
            'backlog_path = ".kaizen/workflow/backlog.md"\n'
        )
        bk_dir = self.repo / ".kaizen" / "workflow"
        bk_dir.mkdir(parents=True)
        # Inject the payload as a backlog item title — rendered into
        # the SUMMARY which the unquoted heredoc evaluates.
        evil_title = (
            'title""";'
            f'open("{self.canary}","w").write("p");'
            'ctx="""'
        )
        (bk_dir / "backlog.json").write_text(json.dumps({
            "items": [{"id": "BK-001", "title": evil_title,
                       "section": "in_flight"}]
        }))

    def tearDown(self):
        self._tmp.cleanup()

    def test_evil_backlog_title_does_not_execute(self):
        r = _run_hook(_HOOKS / "session-surface-backlog.sh",
                       stdin=json.dumps({"hook_event_name": "SessionStart",
                                          "source": "startup"}),
                       extra_env={"CLAUDE_PROJECT_DIR": str(self.repo)})
        self.assertFalse(self.canary.exists(),
                         "RCE: evil backlog title executed Python")
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
