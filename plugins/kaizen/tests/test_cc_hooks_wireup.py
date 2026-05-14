"""Tests for the additive CC-only hook wires (W2 / W3 / W7).

The hooks themselves are best-effort scripts: SubagentStop, SessionEnd,
and Notification only fire under Claude Code. Codex + other hosts
never invoke them. These tests cover the wire-up — manifest entries
exist + scripts are present + scripts parse as valid bash + scripts
emit valid JSON on synthetic input.

Run:
    python3 -m unittest tests.test_cc_hooks_wireup -v
"""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# Manifest path stays at hooks/ root — that's where Claude Code's plugin
# loader discovers it. Scripts categorized by provider live one level
# deeper under hooks/<provider>/.
MANIFEST = PLUGIN_ROOT / "hooks" / "hooks.json"

# CC-only events kaizen now wires (in addition to the 6 pre-existing).
ADDITIVE_EVENTS = ("SubagentStop", "SessionEnd", "Notification")


class TestManifestHasAdditiveEvents(unittest.TestCase):
    """The new CC-only events must be declared in hooks.json."""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_subagentstop_declared(self):
        self.assertIn("SubagentStop", self.data["hooks"])

    def test_sessionend_declared(self):
        self.assertIn("SessionEnd", self.data["hooks"])

    def test_notification_declared(self):
        self.assertIn("Notification", self.data["hooks"])

    def test_each_points_at_existing_script(self):
        for event in ADDITIVE_EVENTS:
            cfg = self.data["hooks"][event]
            self.assertEqual(len(cfg), 1, f"{event}: expected 1 config block")
            commands = cfg[0]["hooks"]
            self.assertGreaterEqual(
                len(commands), 1, f"{event}: expected >= 1 command",
            )
            # Every command's script must exist on disk + live under
            # hooks/claude/ (per the provider-categorization R-PROV
            # convention).
            for c in commands:
                cmd = c["command"]
                self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/claude/", cmd)
                rel = cmd.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].split(" ", 1)[0]
                self.assertTrue(
                    (PLUGIN_ROOT / rel).is_file(),
                    f"{event}: script not found at {rel}",
                )


class TestHookScriptsParseAsBash(unittest.TestCase):
    """All three hook scripts must pass `bash -n` syntax check."""

    def _check(self, name: str):
        p = PLUGIN_ROOT / "hooks" / "claude" / name
        self.assertTrue(p.is_file(), f"missing {p}")
        result = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            f"{name} failed bash -n: {result.stderr}",
        )

    def test_subagentstop_script_parses(self):
        self._check("subagentstop-trace.sh")

    def test_sessionend_script_parses(self):
        self._check("sessionend-drain.sh")

    def test_notification_script_parses(self):
        self._check("notification-surface.sh")


class TestHookScriptsEmitValidJson(unittest.TestCase):
    """Each hook must emit valid JSON on stdout — even on the no-op path."""

    def _run(self, name: str, stdin: str) -> str:
        p = PLUGIN_ROOT / "hooks" / "claude" / name
        result = subprocess.run(
            ["bash", str(p)],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Hooks must always exit 0 (they never block the host).
        self.assertEqual(result.returncode, 0,
                         f"{name} exited {result.returncode}; stderr={result.stderr}")
        return result.stdout.strip()

    def test_subagentstop_emits_envelope(self):
        out = self._run(
            "subagentstop-trace.sh",
            '{"session_id":"s1","subagent_type":"general-purpose","description":"x"}',
        )
        # Should emit a JSON object (empty envelope or with hookSpecificOutput).
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_sessionend_emits_envelope(self):
        out = self._run("sessionend-drain.sh", '{"session_id":"s1"}')
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_notification_emits_envelope(self):
        out = self._run("notification-surface.sh", '{"session_id":"s1"}')
        data = json.loads(out)
        self.assertIsInstance(data, dict)
        # When the gate IS installed (this repo is kaizen-md), Notification
        # surfaces a non-empty additionalContext.
        if "hookSpecificOutput" in data:
            self.assertEqual(
                data["hookSpecificOutput"]["hookEventName"], "Notification"
            )
            self.assertIn("kaizen", data["hookSpecificOutput"]["additionalContext"])


class TestNotificationQuietMode(unittest.TestCase):
    """KAIZEN_NOTIFY_QUIET=1 silences the Notification surface."""

    def test_quiet_emits_empty_envelope(self):
        p = PLUGIN_ROOT / "hooks" / "claude" / "notification-surface.sh"
        result = subprocess.run(
            ["bash", str(p)],
            input='{"session_id":"s1"}',
            capture_output=True,
            text=True,
            env={"KAIZEN_NOTIFY_QUIET": "1", "PATH": "/usr/bin:/bin"},
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.strip()), {})


class TestCrossCliCompatProfile(unittest.TestCase):
    """Verify the hook bodies don't reference CC-only APIs in ways that
    would fail under Codex.

    The contract: hook scripts may use `bash`, `python3`, and kaizen's
    own scripts (trace.py, inbox.py, _plugin_root.sh). They must NOT
    invoke CC-specific CLIs (`claude`, `cc-*`) inside the body — only
    consume the JSON event envelope CC passes on stdin.

    Codex doesn't fire these events, so a forbidden reference wouldn't
    crash at runtime, but it would signal we accidentally added an
    impure dependency.
    """

    FORBIDDEN = (
        "claude ",  # the `claude` CLI
        "/usr/local/bin/claude",
        "cc-",      # legacy CC-specific binaries
    )

    def _check(self, name: str):
        text = (PLUGIN_ROOT / "hooks" / "claude" / name).read_text(encoding="utf-8")
        for needle in self.FORBIDDEN:
            self.assertNotIn(needle, text,
                             f"{name}: CC-specific reference {needle!r} found")

    def test_subagentstop_pure(self):
        self._check("subagentstop-trace.sh")

    def test_sessionend_pure(self):
        self._check("sessionend-drain.sh")

    def test_notification_pure(self):
        self._check("notification-surface.sh")


if __name__ == "__main__":
    unittest.main()
