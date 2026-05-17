"""Tests for userprompt-skill-suggest.sh — auto-suggest hook."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/userprompt-skill-suggest.sh"


class _SandboxHook(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Sandbox the skills/ root via env var (so prod catalog isn't read)
        self.skills_root = self.tmp / "skills"
        self.skills_root.mkdir()
        self._orig = os.environ.get("KAIZEN_SKILL_SUGGEST_ROOT")
        os.environ["KAIZEN_SKILL_SUGGEST_ROOT"] = str(self.skills_root)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_SKILL_SUGGEST_ROOT", None)
        else:
            os.environ["KAIZEN_SKILL_SUGGEST_ROOT"] = self._orig

    def _add_skill(self, name: str, description: str):
        d = self.skills_root / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\nbody\n",
            encoding="utf-8",
        )

    def _fire(self, payload: dict,
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        if env_extra: env.update(env_extra)
        return subprocess.run(
            ["bash", str(_HOOK)],
            input=json.dumps(payload), capture_output=True, text=True,
            timeout=10, env=env,
        )

    def _ctx(self, r: subprocess.CompletedProcess) -> str:
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            return ""
        return out.get("hookSpecificOutput", {}).get("additionalContext", "")


class TestEmitsSuggestionOnMatch(_SandboxHook):
    def test_matching_prompt_lists_skill(self):
        self._add_skill("alpha-skill",
                         'Triggers on "alpha-pattern", "beta-pattern".')
        r = self._fire({"prompt": "apply alpha-pattern here", "session_id": "s"})
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = self._ctx(r)
        self.assertIn("alpha-skill", ctx)
        self.assertIn("kaizen-skill-suggest", ctx)
        self.assertIn("Load Skill", ctx)


class TestSkipsWhenNoMatch(_SandboxHook):
    def test_unrelated_prompt_returns_empty_envelope(self):
        self._add_skill("alpha-skill", 'Triggers on "alpha-pattern".')
        r = self._fire({"prompt": "totally unrelated text", "session_id": "s"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestSkipsWhenNoPrompt(_SandboxHook):
    def test_missing_prompt_field(self):
        self._add_skill("alpha-skill", 'Triggers on "alpha-pattern".')
        r = self._fire({"session_id": "s"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestBypassEnv(_SandboxHook):
    def test_KAIZEN_SKILL_SUGGEST_DISABLE(self):
        self._add_skill("alpha-skill", 'Triggers on "alpha-pattern".')
        r = self._fire({"prompt": "alpha-pattern", "session_id": "s"},
                        env_extra={"KAIZEN_SKILL_SUGGEST_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "{}")


class TestMalformedJsonGraceful(_SandboxHook):
    def test_garbage_stdin_no_crash(self):
        r = subprocess.run(
            ["bash", str(_HOOK)],
            input="not json", capture_output=True, text=True,
            timeout=5, env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")


class TestEnvelopeShape(_SandboxHook):
    def test_event_name_is_user_prompt_submit(self):
        self._add_skill("a", 'Triggers on "trigger-phrase".')
        r = self._fire({"prompt": "trigger-phrase", "session_id": "s"})
        out = json.loads(r.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")


class TestUserPromptFieldFallback(_SandboxHook):
    """CC may shape the prompt field as 'prompt' OR 'user_prompt'."""

    def test_user_prompt_field_also_works(self):
        self._add_skill("a", 'Triggers on "trigger-phrase".')
        r = self._fire({"user_prompt": "trigger-phrase here", "session_id": "s"})
        ctx = self._ctx(r)
        self.assertIn("a", ctx)


if __name__ == "__main__":
    unittest.main()
