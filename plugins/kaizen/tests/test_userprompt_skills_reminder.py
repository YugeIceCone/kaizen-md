"""Tests for userprompt-skills-reminder.sh — per-prompt discipline pin."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/userprompt-skills-reminder.sh"


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

    def _write_mode(self, mode: str, skills: list[str]):
        (self.repo / ".kaizen" / "session-mode.json").write_text(json.dumps({
            "mode": mode, "skills": skills, "bundles": [], "session_id": "",
            "set_at": "2026-05-17T00:00:00Z",
        }))

    def _ctx(self, r: subprocess.CompletedProcess) -> str:
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            return ""
        return out.get("hookSpecificOutput", {}).get("additionalContext", "")


class TestNoSessionModeSkips(Base):
    def test_no_state_file_returns_empty(self):
        r = self._fire()
        self.assertEqual(r.stdout.strip(), "{}")


class TestNoSkillsSkips(Base):
    def test_empty_skills_array_no_op(self):
        self._write_mode("neither", [])
        r = self._fire()
        self.assertEqual(r.stdout.strip(), "{}")


class TestRemindsActiveSkills(Base):
    def test_pinned_skills_appear_in_reminder(self):
        self._write_mode("loop", ["kiss", "dry", "tdd"])
        r = self._fire()
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = self._ctx(r)
        self.assertIn("kaizen disciplines pinned", ctx)
        self.assertIn("kiss", ctx)
        self.assertIn("dry", ctx)
        self.assertIn("tdd", ctx)
        # Descriptions must appear too — bare ids would be useless
        self.assertIn("RED first", ctx)  # tdd description fragment
        self.assertIn("keep it simple", ctx)  # kiss


class TestSkipsBypassEnv(Base):
    def test_KAIZEN_SKILLS_REMINDER_DISABLE_returns_empty(self):
        self._write_mode("loop", ["kiss"])
        r = self._fire(env_extra={"KAIZEN_SKILLS_REMINDER_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestSkipsOutsideGitRepo(Base):
    def test_non_git_dir_no_op(self):
        outside = self.repo.parent / "_not_a_repo"
        outside.mkdir(exist_ok=True)
        try:
            r = subprocess.run(
                ["bash", str(_HOOK)], input="{}",
                capture_output=True, text=True, timeout=5,
                cwd=str(outside), env=os.environ.copy(),
            )
            self.assertEqual(r.stdout.strip(), "{}")
        finally:
            outside.rmdir()


class TestEnvelopeShape(Base):
    def test_emits_user_prompt_submit_event_name(self):
        self._write_mode("loop", ["kiss"])
        r = self._fire()
        out = json.loads(r.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )


class TestUnknownSkillsAllSkippedNoEmit(Base):
    """If all pinned skills are unknown (typos), reminder is empty
    → hook should emit {} rather than an empty additionalContext."""
    def test_only_unknown_skills_no_emit(self):
        self._write_mode("loop", ["nonexistent-1", "nonexistent-2"])
        r = self._fire()
        self.assertEqual(r.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
