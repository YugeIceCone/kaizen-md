"""Smoke tests for brain hooks: brain-session-end.sh + brain-user-prompt.sh.

Verifies:
- Both hook scripts exist + are executable
- They exit 0 even on missing input (defensive)
- They respect their bypass env vars
- They appear in hooks/hooks.json at the expected event slots
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK_DIR = _KZ_DIR / "hooks/claude"


class TestHookScripts(unittest.TestCase):
    def test_session_end_executable(self):
        h = _HOOK_DIR / "brain-session-end.sh"
        self.assertTrue(h.is_file())
        self.assertTrue(os.access(h, os.X_OK), f"{h} must be executable")

    def test_user_prompt_executable(self):
        h = _HOOK_DIR / "brain-user-prompt.sh"
        self.assertTrue(h.is_file())
        self.assertTrue(os.access(h, os.X_OK), f"{h} must be executable")

    def test_user_prompt_bypass_env(self):
        """KAIZEN_BRAIN_PROMPT_DISABLE=1 short-circuits to exit 0."""
        h = _HOOK_DIR / "brain-user-prompt.sh"
        env = os.environ.copy()
        env["KAIZEN_BRAIN_PROMPT_DISABLE"] = "1"
        result = subprocess.run(
            ["bash", str(h)],
            input=json.dumps({"user_prompt": "remember this please"}),
            capture_output=True, text=True, env=env, timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        # Bypass mode should produce NO stderr breadcrumb
        self.assertEqual(result.stderr.strip(), "")

    def test_user_prompt_detects_trigger(self):
        """When a capture trigger appears in the prompt, hook emits
        a breadcrumb to stderr."""
        h = _HOOK_DIR / "brain-user-prompt.sh"
        # Force the bypass off explicitly
        env = os.environ.copy()
        env.pop("KAIZEN_BRAIN_PROMPT_DISABLE", None)
        result = subprocess.run(
            ["bash", str(h)],
            input=json.dumps({"user_prompt": "please remember this for next time"}),
            capture_output=True, text=True, env=env, timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("capture trigger", result.stderr)

    def test_user_prompt_no_trigger_silent(self):
        """No trigger → no stderr."""
        h = _HOOK_DIR / "brain-user-prompt.sh"
        env = os.environ.copy()
        env.pop("KAIZEN_BRAIN_PROMPT_DISABLE", None)
        result = subprocess.run(
            ["bash", str(h)],
            input=json.dumps({"user_prompt": "what is the weather today"}),
            capture_output=True, text=True, env=env, timeout=5,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr.strip(), "")

    def test_session_end_bypass_env(self):
        """KAIZEN_BRAIN_AUDIT_DISABLE=1 short-circuits to exit 0."""
        h = _HOOK_DIR / "brain-session-end.sh"
        env = os.environ.copy()
        env["KAIZEN_BRAIN_AUDIT_DISABLE"] = "1"
        result = subprocess.run(
            ["bash", str(h)],
            capture_output=True, text=True, env=env, timeout=5,
        )
        self.assertEqual(result.returncode, 0)


class TestHooksJson(unittest.TestCase):
    """Verify the brain hooks are wired into hooks/hooks.json at the
    expected event slots."""

    def setUp(self):
        with open(_KZ_DIR / "hooks/hooks.json") as f:
            self.cfg = json.load(f)

    def test_brain_user_prompt_in_userprompt_submit(self):
        cmds = []
        for group in self.cfg["hooks"].get("UserPromptSubmit", []):
            for h in group.get("hooks", []):
                cmds.append(h.get("command", ""))
        self.assertTrue(
            any("brain-user-prompt.sh" in c for c in cmds),
            "brain-user-prompt.sh must be wired into UserPromptSubmit",
        )

    def test_brain_session_end_in_sessionend(self):
        cmds = []
        for group in self.cfg["hooks"].get("SessionEnd", []):
            for h in group.get("hooks", []):
                cmds.append(h.get("command", ""))
        self.assertTrue(
            any("brain-session-end.sh" in c for c in cmds),
            "brain-session-end.sh must be wired into SessionEnd",
        )


class TestPluginManifest(unittest.TestCase):
    def test_brain_scripts_in_permissions(self):
        with open(_KZ_DIR / ".claude-plugin/plugin.json") as f:
            manifest = json.load(f)
        perms = manifest.get("permissions", {}).get("allow", [])
        for script in (
            "brain.py", "brain_index.py", "brain_promote.py",
            "brain_audit.py", "brain_evolve.py", "brain_mcp.py",
        ):
            # Accept either a specific entry or a wildcard (*.py) that covers all scripts
            covered = any(script in p or "*.py" in p for p in perms)
            self.assertTrue(
                covered,
                f"plugin.json missing permission for {script}",
            )


if __name__ == "__main__":
    unittest.main()
