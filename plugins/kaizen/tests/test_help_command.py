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
                         "kaizen-status"):
            self.assertIn(pointer, self.body, f"missing pointer: {pointer}")

    def test_under_165_lines(self):
        """Body budget — tight per-command descriptions but bounded.
        Loosened progressively as the command surface grew:
          120 → 150 (added /kaizen:intent + /kaizen:audit:axis)
          150 → 165 (added the QA wizard preamble + /kaizen:discovery)."""
        self.assertLess(self.body.count("\n"), 165,
                         "help body should be precise+concise (~165 lines max for ~60 commands)")

    def test_each_command_has_description(self):
        """Per-command row format: `command` | description.
        Spot-check a few clusters to ensure descriptions are present.
        Fixture uses only permanent roots — slashes that survive the
        consolidate-2 D1-D7 fold."""
        for cmd in ("audit", "audit:axis", "memory-ledger",
                     "setup", "onboard", "observe"):
            # row format: `cmd` | <description>
            self.assertRegex(self.body, rf"`{cmd}`\s*\|",
                              f"missing per-command row for {cmd}")

    def test_body_includes_qa_wizard_preamble(self):
        """User-direction: /kaizen:help gets a simple-list QA (cluster
        picker). Body must instruct the agent to run the wizard when
        called with no args."""
        self.assertRegex(self.body,
                          r"(?i)interactive (cluster )?wizard|cluster picker",
                          "missing QA wizard preamble heading")
        # The wizard contract names the 4 visible cluster options.
        for label in ("audit/quality", "workflow", "observability",
                       "brain/memory"):
            self.assertIn(label, self.body,
                           f"QA wizard must list cluster option: {label}")

    def test_body_lists_cluster_subcommand(self):
        """The agent dispatches `kaizen-help-gen cluster <name>` to
        render one cluster's sub-table after the user picks."""
        self.assertIn("kaizen-help-gen cluster", self.body,
                       "QA wizard must reference cluster dispatch")


if __name__ == "__main__":
    unittest.main()
