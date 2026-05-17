"""Tests for session-intake.sh — the SessionStart QA hook."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/session-intake.sh"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / ".kaizen").mkdir()

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()

    def _fire(self, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_extra: env.update(env_extra)
        return subprocess.run(
            ["bash", str(_HOOK)],
            input="{}", capture_output=True, text=True,
            timeout=10, cwd=str(self.repo), env=env,
        )

    def _additional_context(self, r: subprocess.CompletedProcess) -> str:
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            return ""
        return out.get("hookSpecificOutput", {}).get("additionalContext", "")


class TestEmitsIntakePromptWhenUnset(Base):
    def test_clean_repo_emits_intake_prompt(self):
        r = self._fire()
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = self._additional_context(r)
        self.assertIn("AskUserQuestion", ctx)
        self.assertIn("Loop", ctx)
        self.assertIn("Workflow", ctx)
        self.assertIn("Neither", ctx)
        self.assertIn("kaizen-session-mode set", ctx)

    def test_includes_bundles_question(self):
        """Q2 must instruct multiSelect bundles."""
        r = self._fire()
        ctx = self._additional_context(r)
        self.assertIn("Disciplines", ctx)
        self.assertIn("Simplicity", ctx)
        self.assertIn("Structure", ctx)
        self.assertIn("Process", ctx)
        self.assertIn("Karpathy", ctx)
        self.assertIn("--bundles", ctx)

    def test_prescribes_single_command_for_persistence(self):
        """Mode + bundles persist via ONE call, not two."""
        r = self._fire()
        ctx = self._additional_context(r)
        self.assertIn("kaizen-session-mode set", ctx)
        # The example line shows mode + --bundles together
        self.assertIn("--bundles", ctx)

    def test_includes_threshold_question(self):
        """Q3 must ask about auto-handoff context-pressure threshold."""
        r = self._fire()
        ctx = self._additional_context(r)
        self.assertIn("Auto-handoff", ctx)
        for pct in ("25%", "50%", "75%", "85%"):
            self.assertIn(pct, ctx)
        self.assertIn("Disabled", ctx)
        self.assertIn("--threshold", ctx)


class TestSkipsWhenAlreadySet(Base):
    def test_existing_session_mode_skips(self):
        (self.repo / ".kaizen" / "session-mode.json").write_text(
            json.dumps({"mode": "loop"}))
        r = self._fire()
        self.assertEqual(r.stdout.strip(), "{}")


class TestSkipsWhenLoopActive(Base):
    def test_active_loop_state_skips(self):
        (self.repo / ".kaizen" / "loop.state.md").write_text(
            "---\nactive: true\n---\n{}\n")
        r = self._fire()
        self.assertEqual(r.stdout.strip(), "{}")


class TestSkipsWhenWorkflowInProgress(Base):
    def test_incomplete_workflow_skips(self):
        (self.repo / ".kaizen" / "workflow").mkdir()
        (self.repo / ".kaizen" / "workflow" / "state.json").write_text(
            json.dumps({"stages": ["a", "b", "c"], "current": 1}))
        r = self._fire()
        self.assertEqual(r.stdout.strip(), "{}")


class TestEmitsWhenWorkflowComplete(Base):
    """A workflow that already finished should NOT block the intake —
    the mode for the NEXT session is still up for grabs."""
    def test_complete_workflow_does_not_block(self):
        (self.repo / ".kaizen" / "workflow").mkdir()
        (self.repo / ".kaizen" / "workflow" / "state.json").write_text(
            json.dumps({"stages": ["a", "b"], "current": 2}))
        r = self._fire()
        ctx = self._additional_context(r)
        self.assertIn("AskUserQuestion", ctx)


class TestBypassEnv(Base):
    def test_KAIZEN_SESSION_INTAKE_DISABLE_returns_empty(self):
        r = self._fire(env_extra={"KAIZEN_SESSION_INTAKE_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestNotGitRepoSkips(Base):
    """Outside a git repo we have no .kaizen/ to write into — silent skip."""
    def test_no_git_repo_no_op(self):
        non_repo = self.repo.parent / "_not_a_repo"
        non_repo.mkdir(exist_ok=True)
        try:
            r = subprocess.run(
                ["bash", str(_HOOK)], input="{}",
                capture_output=True, text=True, timeout=5,
                cwd=str(non_repo), env=os.environ.copy(),
            )
            self.assertEqual(r.stdout.strip(), "{}")
        finally:
            non_repo.rmdir()


class TestEmitsValidJson(Base):
    def test_envelope_parses_as_json(self):
        r = self._fire()
        # Must round-trip through json.loads (catches quoting bugs)
        out = json.loads(r.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["hookEventName"], "SessionStart")


if __name__ == "__main__":
    unittest.main()
