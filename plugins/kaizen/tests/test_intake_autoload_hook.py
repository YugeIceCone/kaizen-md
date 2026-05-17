"""Tests for userprompt-intake-autoload — closes the Phase 10 loop.

The hook fires on UserPromptSubmit, matches the prompt against
intake-checklist triggers, and emits the skills bundle as a
systemMessage. Agent loads the right skills before writing code.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/userprompt-intake-autoload.sh"


def _fire(prompt: str, env_extra: dict | None = None) -> dict:
    """Invoke the hook with a synthetic UserPromptSubmit event;
    parse its stdout (hook-decision JSON or empty {})."""
    event = json.dumps({"prompt": prompt, "session_id": "test-sid"})
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(["bash", str(_HOOK)], input=event,
                        capture_output=True, text=True, timeout=10,
                        env=env)
    if r.returncode != 0:
        return {"_returncode": r.returncode, "_stderr": r.stderr}
    out = r.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"_raw": out}


class TestArtifact(unittest.TestCase):
    def test_hook_present_and_executable(self):
        self.assertTrue(_HOOK.is_file())
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_hook_wired_into_hooks_json(self):
        hooks_json = _KZ_DIR / "hooks/hooks.json"
        data = json.loads(hooks_json.read_text())
        ups = data["hooks"].get("UserPromptSubmit", [])
        cmds = [h["command"]
                for block in ups
                for h in block.get("hooks", [])]
        self.assertTrue(any("userprompt-intake-autoload" in c for c in cmds),
                          f"hook not wired into UserPromptSubmit: {cmds}")

    def test_permission_in_plugin_json(self):
        plugin_json = _KZ_DIR / ".claude-plugin/plugin.json"
        data = json.loads(plugin_json.read_text())
        allow = data["permissions"]["allow"]
        self.assertTrue(any("userprompt-intake-autoload" in e for e in allow))


class TestBehavior(unittest.TestCase):
    def test_match_emits_systemMessage_with_bundle(self):
        out = _fire("add a new mcp server to the plugin")
        self.assertIn("systemMessage", out, out)
        msg = out["systemMessage"]
        self.assertIn("kaizen-intake", msg)
        self.assertIn("new-mcp-server", msg)
        self.assertIn("Skill(plugin:plugin-development)", msg)
        self.assertIn("Skill(plugin:schema-driven-cli)", msg)

    def test_miss_emits_empty_json(self):
        out = _fire("what is the weather today")
        self.assertEqual(out, {})

    def test_short_prompt_short_circuits(self):
        out = _fire("hi")
        self.assertEqual(out, {})

    def test_disable_env_silences(self):
        out = _fire("add a new mcp server",
                     env_extra={"KAIZEN_INTAKE_AUTOLOAD_DISABLE": "1"})
        self.assertEqual(out, {})

    def test_bug_fix_trigger_matches(self):
        out = _fire("fix this bug in the gold miner pipeline")
        self.assertIn("systemMessage", out, out)
        self.assertIn("bug-fix", out["systemMessage"])
        self.assertIn("Skill(plugin:tdd)", out["systemMessage"])

    def test_malformed_event_no_crash(self):
        """Hook must handle bad stdin gracefully — never break the
        host prompt cycle."""
        r = subprocess.run(["bash", str(_HOOK)], input="not-json",
                            capture_output=True, text=True, timeout=10,
                            env=os.environ.copy())
        self.assertEqual(r.returncode, 0,
                          f"hook crashed on malformed event: {r.stderr}")
        self.assertEqual(r.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
