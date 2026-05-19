"""Tests for gold-precompact hook — surfaces un-promoted captures
before context compaction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HOOK = _KZ_DIR / "hooks/claude/gold-precompact.sh"


def _fire(env: dict | None = None,
          stdin: str = '{"trigger": "manual"}') -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_HOOK)],
        input=stdin, capture_output=True, text=True,
        timeout=5, env={**os.environ, **(env or {})},
    )


class TestHookArtifacts(unittest.TestCase):
    def test_hook_exists_and_executable(self):
        self.assertTrue(_HOOK.is_file())
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_hook_wired_into_hooks_json(self):
        """gold-precompact must be registered under PreCompact."""
        hooks_json = _KZ_DIR / "hooks/hooks.json"
        data = json.loads(hooks_json.read_text())
        precompact = data["hooks"].get("PreCompact", [])
        cmds = [h["command"]
                for block in precompact
                for h in block.get("hooks", [])]
        self.assertTrue(any("gold-precompact" in c for c in cmds),
                          f"gold-precompact not wired into PreCompact: {cmds}")

    def test_hook_permission_in_plugin_json(self):
        """Hook path must be whitelisted in plugin.json::permissions.allow."""
        plugin_json = _KZ_DIR / ".claude-plugin/plugin.json"
        data = json.loads(plugin_json.read_text())
        allow = data["permissions"]["allow"]
        self.assertTrue(any("gold-precompact" in entry for entry in allow),
                          f"gold-precompact not permitted: {allow}")


class TestHookBehavior(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.store = self.tmp / "gold.jsonl"
        self.env = {"KAIZEN_GOLD_FILE": str(self.store)}

    def tearDown(self):
        self._tmp.cleanup()

    def _capture(self, *patterns):
        gold_py = _KZ_DIR / "scripts/gold/gold.py"
        for p in patterns:
            subprocess.run([sys.executable, str(gold_py), "capture", p],
                            capture_output=True, text=True, timeout=5,
                            env={**os.environ, **self.env})

    def test_empty_store_emits_empty_json(self):
        r = _fire(env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")

    def test_unpromoted_entries_emit_systemMessage(self):
        self._capture("alpha", "beta", "gamma")
        r = _fire(env=self.env)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertIn("systemMessage", out)
        msg = out["systemMessage"]
        self.assertIn("kaizen-gold", msg)
        self.assertIn("3", msg)  # 3 un-promoted captures

    def test_disabled_env_skips_silently(self):
        self._capture("present-but-disabled")
        env = {**self.env, "KAIZEN_GOLD_DISABLE": "1"}
        r = _fire(env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")

    def test_all_promoted_emits_empty_json(self):
        """When everything is promoted there is nothing to surface."""
        self._capture("alpha")
        gold_py = _KZ_DIR / "scripts/gold/gold.py"
        target = self.tmp / "rules.md"
        subprocess.run([sys.executable, str(gold_py), "promote", "1",
                         "--to", str(target)],
                        capture_output=True, text=True, timeout=5,
                        env={**os.environ, **self.env})
        r = _fire(env=self.env)
        self.assertEqual(r.stdout.strip(), "{}")


if __name__ == "__main__":
    unittest.main()
