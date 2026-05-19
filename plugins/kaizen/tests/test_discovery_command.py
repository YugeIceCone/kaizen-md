"""Contract tests for the new /kaizen:discovery wrapper (P5 of the
menu-consolidation plan). Single AskUserQuestion entry point that
bundles onboard / knowledge / claude-docs / scrape.

Shape:
  Q1 [multiSelect]: What to index? (4 surfaces — codebase / knowledge
    / claude-docs / web)
  Q2 [single]: Action? (build-refresh / search / stats)

Per pick, agent dispatches the underlying slash with the matching verb.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/discovery.md"


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

    def test_name_is_discovery(self):
        self.assertIn("name: discovery", self.fm)

    def test_description_quoted_triggers_min_3(self):
        """frontmatter-coverage axis."""
        quoted = re.findall(r"\"[^\"\n]{2,}\"|'[^'\n]{2,}'", self.fm)
        self.assertGreaterEqual(len(quoted), 3)

    def test_argument_hint_present(self):
        self.assertIn("argument-hint:", self.fm)

    def test_allowed_tools_grants_askuserquestion(self):
        self.assertIn("AskUserQuestion", self.fm)


class TestBodyContract(unittest.TestCase):
    def setUp(self):
        self.body = _CMD.read_text(encoding="utf-8")

    def test_two_question_wizard_section_present(self):
        self.assertRegex(self.body, r"(?i)question\s*1\s*[—-]")
        self.assertRegex(self.body, r"(?i)question\s*2\s*[—-]")

    def test_q1_multiselect_lists_4_surfaces(self):
        """Q1 must offer the 4 discovery surfaces (codebase / knowledge
        / claude-docs / web). Labels are user-visible; the slash
        mappings live in the body's arg-assembly table."""
        for surface in ("onboard", "knowledge", "claude-docs", "scrape"):
            self.assertIn(surface, self.body,
                           f"Q1 wizard must reference underlying slash: {surface}")

    def test_q2_single_pick_action_options(self):
        """Q2 must cover the 3 common actions across all surfaces."""
        for action in ("search", "index", "stats"):
            # Each action appears as a Q2 option label or dispatch row
            self.assertRegex(self.body, rf"(?i)\b{action}\b")

    def test_arg_assembly_table_present(self):
        """The body documents which slash each Q1×Q2 combo dispatches."""
        self.assertRegex(self.body, r"(?i)arg[- ]assembly|dispatch")
        # The 4 underlying slash names must be referenced (already
        # covered by test_q1_multiselect, but pinning here as the
        # arg-assembly contract).
        for slash in ("kaizen-onboard", "kaizen-knowledge",
                       "kaizen-claude-docs", "kaizen-scrape"):
            self.assertIn(slash, self.body, f"arg-assembly missing: {slash}")

    def test_q3_embed_model_picker_always_fires(self):
        """Q3 fires after Q1+Q2 regardless of Q2 — the user can
        always pick or change the embedding model. Per-action semantics
        are documented in a body table (see test_q3_per_action_semantics)."""
        self.assertRegex(self.body, r"(?i)question\s*3\s*[—-]")
        self.assertIn("discovery_list_embed_models", self.body)
        # Default option present
        self.assertRegex(self.body, r"(?i)current model|default")
        # Q3 must NOT be gated to one Q2 branch — body wording must
        # signal "always" / "regardless"
        self.assertRegex(self.body, r"(?i)always|regardless|after Q1\+Q2")

    def test_q3_per_action_semantics_documented(self):
        """Each Q2 action must have a documented Q3-pick semantics
        (no-op for Search, re-embed for Index, pin-or-followup for Stats)."""
        for action_term in ("search", "index", "stats"):
            # Either appears in the per-action table, or in narrative
            self.assertRegex(self.body, rf"(?i)\b{action_term}\b")
        # Pin path is referenced (kaizen-models pin-embed)
        self.assertIn("pin-embed", self.body)

    def test_body_lists_mcp_tools(self):
        """The body surfaces the agent-callable MCP surface so the
        agent can bypass the wizard when programmatic."""
        for tool in ("discovery_search", "discovery_stats",
                     "discovery_list_surfaces",
                     "discovery_list_embed_models"):
            self.assertIn(tool, self.body, f"MCP tool not surfaced: {tool}")


if __name__ == "__main__":
    unittest.main()
