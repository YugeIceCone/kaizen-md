"""Auto-loader coverage tests — verifies the intent system surfaces
the right kaizen command for representative user prompts. Catches
regex regressions in intents.yaml the moment they ship."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_INTENT = _KZ_DIR / "skills/workflow/scripts/intent.py"
_INTENTS_YAML = _KZ_DIR / "skills/intent/domain/intents.yaml"


def _suggest(text: str) -> dict | None:
    """Run `kaizen-intent suggest --text X --json` and return the
    matched intent dict (or None on no match)."""
    r = subprocess.run(
        [sys.executable, str(_INTENT), "suggest", "--text", text, "--json"],
        capture_output=True, text=True, timeout=10,
        env=os.environ.copy(),
    )
    if r.returncode != 0:
        return None
    payload = json.loads(r.stdout)
    return payload.get("data", {}).get("intent")


class TestRuleCount(unittest.TestCase):
    """We grew from 15 → 30+ rules in the auto-loader pass. Pin a
    floor so accidental deletions are caught."""

    def test_intents_yaml_has_at_least_30_rules(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        data = yaml.safe_load(_INTENTS_YAML.read_text())
        self.assertGreaterEqual(len(data["intents"]), 30,
                                  f"intent rule count regressed: {len(data['intents'])}")


class TestAutoloaderMatches(unittest.TestCase):
    """Each row: prompt → expected intent id. Catches when a regex
    breaks on a representative phrase."""

    CASES: list[tuple[str, str]] = [
        # plugin-development hub routing
        ("add a new mcp server to the plugin",       "plugin-dev-intake"),
        ("which skills should I load for this?",     "plugin-dev-intake"),
        ("dispatch a subagent for tdd in worktree",  "plugin-dev-dispatch"),
        # audit-axis routing
        ("what is untested in the plugin?",          "audit-coverage"),
        ("coverage gap report",                       "audit-coverage"),
        ("schema coverage",                           "audit-schema-coverage"),
        ("filename intent match",                     "audit-name-quality"),
        ("frontmatter audit please",                  "audit-frontmatter"),
        ("token bloat scan",                          "audit-token-bloat"),
        # lifecycle commands
        ("install the kaizen plugin",                 "plugin-install"),
        ("update the kaizen plugin",                  "plugin-update"),
        ("kaizen plugin health",                      "plugin-health"),
        ("backup the state",                          "plugin-backup"),
        # one-off helpers
        ("capture this gold pattern",                 "gold-capture"),
        ("show me kaizen metrics",                    "metrics-skips"),
        ("onboard this codebase",                     "discover-codebase"),
        ("claude api docs for hook payloads",         "discover-claude-docs"),
    ]

    def test_each_prompt_resolves_to_expected_intent(self):
        for prompt, expected in self.CASES:
            with self.subTest(prompt=prompt):
                got = _suggest(prompt)
                got_id = got["id"] if got else None
                self.assertEqual(got_id, expected,
                                  f"prompt {prompt!r} → {got_id!r} (expected {expected!r})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
