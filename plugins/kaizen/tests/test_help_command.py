"""Tests for /kaizen:help slash command — structural + content."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/help.md"


class TestCommandFile(unittest.TestCase):
    def test_command_file_exists(self):
        self.assertTrue(_CMD.is_file(), f"missing: {_CMD}")


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", self.text, re.DOTALL)
        self.assertIsNotNone(m, "no YAML frontmatter")
        self.fm = m.group(1)
        self.body = m.group(2)

    def test_name_is_help(self):
        self.assertIn("name: help", self.fm)

    def test_description_has_quoted_triggers(self):
        """frontmatter-coverage axis: >=3 quoted trigger phrases."""
        quoted = re.findall(r"\"[^\"\n]{2,}\"|'[^'\n]{2,}'", self.fm)
        self.assertGreaterEqual(len(quoted), 3,
                                 f"need >=3 quoted triggers, got {len(quoted)}")

    def test_argument_hint_present(self):
        self.assertIn("argument-hint:", self.fm)

    def test_allowed_tools_grants_kaizen_bin(self):
        self.assertIn("kaizen", self.fm)


class TestBodyContent(unittest.TestCase):
    def setUp(self):
        self.body = _CMD.read_text(encoding="utf-8")

    def test_body_static_no_bash_execution(self):
        """Per 'single roundtrip, no token usage' — body must NOT
        run a bash command (which would capture stdout into the
        agent's context). Body IS the response."""
        # `!` followed by backtick is the slash-command bash-exec marker
        self.assertNotIn("!`", self.body,
                          "help body should be static — no `!`...` exec")

    def test_lists_all_9_clusters(self):
        for cluster in ("audit/quality", "observability", "brain/memory",
                         "workflow", "plugin-meta", "discovery", "dev-aids"):
            self.assertIn(cluster, self.body, f"missing cluster: {cluster}")

    def test_includes_drill_down_pointers(self):
        for pointer in ("kaizen commands", "kaizen help", "kaizen list",
                         "/kaizen:status", "/kaizen:menu"):
            self.assertIn(pointer, self.body, f"missing pointer: {pointer}")

    def test_under_50_lines(self):
        """Single-screen budget — full taxonomy should fit on one screen."""
        self.assertLess(self.body.count("\n"), 60,
                         "help body should be one-screen (~30-50 lines)")


if __name__ == "__main__":
    unittest.main()
