"""Tests for the forked-skill wire-up (code-tour / karpathy / self-improving)."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_COMMANDS = _KZ_DIR / "commands"
_BIN = _KZ_DIR / "bin"


class TestCodeTourCommand(unittest.TestCase):
    def setUp(self):
        self.cmd = _COMMANDS / "code-tour.md"

    def test_command_file_exists(self):
        self.assertTrue(self.cmd.is_file())

    def test_frontmatter_has_name_and_argument_hint(self):
        text = self.cmd.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(m)
        fm = m.group(1)
        self.assertIn("name: code-tour", fm)
        self.assertIn("argument-hint:", fm)

    def test_body_references_skill_and_domain_yamls(self):
        body = self.cmd.read_text(encoding="utf-8")
        self.assertIn("Skill(kaizen:code-tour)", body)
        self.assertIn("personas.yaml", body)
        self.assertIn("depths.yaml", body)


class TestSelfImprovingCommand(unittest.TestCase):
    def setUp(self):
        self.cmd = _COMMANDS / "self-improving.md"

    def test_command_file_exists(self):
        self.assertTrue(self.cmd.is_file())

    def test_subcommands_documented(self):
        body = self.cmd.read_text(encoding="utf-8")
        for sub in ("review", "promote", "extract", "health"):
            self.assertIn(f"### `{sub}", body,
                          f"subcommand {sub!r} not documented")

    def test_links_writing_skills_for_extract(self):
        body = self.cmd.read_text(encoding="utf-8")
        self.assertIn("Skill(kaizen:writing-skills)", body)


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
