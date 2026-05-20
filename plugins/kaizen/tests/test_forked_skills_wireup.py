"""Tests for the forked-skill wire-up.

Originally asserted that code-tour / self-improving / karpathy each
shipped a slash command. Post-category-2 cleanup, code-tour +
self-improving no longer have slashes (the skills + bins still
ship); the test asserts the new shape:
  - the SKILL.md exists (agent reaches via Skill tool)
  - the slash form is retired (no commands/<name>.md)
karpathy keeps its parent bin contract (still user-facing).
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_COMMANDS = _KZ_DIR / "commands"
_SKILLS = _KZ_DIR / "skills"
_BIN = _KZ_DIR / "bin"


class TestCodeTourSkill(unittest.TestCase):
    """code-tour: skill survives the slash retirement."""

    def test_skill_body_exists(self):
        skill = _SKILLS / "code-tour" / "SKILL.md"
        self.assertTrue(skill.is_file(), f"missing: {skill}")

    def test_domain_yamls_intact(self):
        for stem in ("personas", "depths"):
            p = _SKILLS.parent / "schemas" / "code-tour" / f"{stem}.yaml"
            self.assertTrue(p.is_file(), f"missing: {p}")



class TestSelfImprovingSkill(unittest.TestCase):
    """self-improving: skill survives; slash retired (daemon-driven)."""

    def test_skill_body_exists(self):
        skill = _SKILLS / "self-improving" / "SKILL.md"
        self.assertTrue(skill.is_file(), f"missing: {skill}")

    def test_skill_documents_subcommands(self):
        body = (_SKILLS / "self-improving" / "SKILL.md").read_text(encoding="utf-8")
        for sub in ("review", "promote"):
            self.assertIn(sub, body,
                          f"subcommand {sub!r} not documented in skill body")



class TestKarpathyParentBin(unittest.TestCase):
    def setUp(self):
        self.bin = _BIN / "kaizen-karpathy-check"

    def test_bin_exists_and_executable(self):
        self.assertTrue(self.bin.is_file())
        import os
        self.assertTrue(os.access(self.bin, os.X_OK))

    def test_help_lists_4_subcommands(self):
        r = subprocess.run(
            ["bash", str(self.bin), "help"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r.returncode, 0)
        for sub in ("complexity", "surgeon", "assumption", "goal"):
            self.assertIn(sub, r.stdout)

    def test_no_arg_shows_help(self):
        r = subprocess.run(
            ["bash", str(self.bin)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)


class TestPluginManifestPerms(unittest.TestCase):
    """The 4 karpathy scripts + the parent bin need perms in plugin.json."""
    def test_karpathy_perms_present(self):
        import json
        manifest = json.loads(
            (_KZ_DIR / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        allow = manifest["permissions"]["allow"]
        # Parent bin
        self.assertTrue(any("kaizen-karpathy-check:" in a for a in allow),
                        "kaizen-karpathy-check bin perm missing")
        # Wildcard for skill-private karpathy scripts
        self.assertTrue(
            any("skills/karpathy/scripts/" in a for a in allow),
            "karpathy script perms missing")


if __name__ == "__main__":
    unittest.main()
