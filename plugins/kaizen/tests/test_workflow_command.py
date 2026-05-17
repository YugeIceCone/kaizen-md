"""Contract tests for /kaizen:workflow slash command (P2 of the
menu-consolidation plan). Pins the 4-question wizard + arg-assembly
table; if the structure drifts, this test fires.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/workflow.md"


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()
        self.fm = _frontmatter(self.text)

    def test_workflow_command_present(self):
        self.assertTrue(_CMD.is_file())

    def test_name_is_workflow(self):
        self.assertIn("name: workflow", self.fm)

    def test_allowed_tools_includes_AskUserQuestion(self):
        self.assertIn("AskUserQuestion", self.fm)

    def test_allowed_tools_includes_workflow_config_bin(self):
        self.assertIn("kaizen-workflow-config", self.fm)

    def test_argument_hint_documents_4q_wizard(self):
        self.assertIn("4-Q", self.fm)
        self.assertIn("empty", self.fm.lower())

    def test_description_distinguishes_from_session_mode(self):
        """Body must call out the session-mode vs workflow distinction
        so future authors don't merge the two."""
        self.assertIn("session-mode", self.fm.lower())
        self.assertIn("default", self.fm.lower())


class TestFourQuestions(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_exactly_four_numbered_questions(self):
        qs = re.findall(r"### Question (\d+)", self.text)
        self.assertEqual(sorted(qs), ["1", "2", "3", "4"],
                          f"expected Q1-Q4; got {qs}")

    def test_q1_scope_options(self):
        q1 = self.text.split("### Question 1")[1].split("### Question 2")[0]
        for token in ("This project", "User-global"):
            self.assertIn(token, q1, f"Q1 missing scope option: {token}")
        for path in (".kaizen/workflow.json", "workflow-global.json"):
            self.assertIn(path, q1, f"Q1 missing storage path: {path}")

    def test_q2_run_mode_three_options(self):
        q2 = self.text.split("### Question 2")[1].split("### Question 3")[0]
        for label in ("Routine", "Loop", "Schema"):
            self.assertIn(label, q2)

    def test_q3_disciplines_multiselect(self):
        q3 = self.text.split("### Question 3")[1].split("### Question 4")[0]
        self.assertIn("multiSelect: true", q3,
                       "Q3 (disciplines) must be multiSelect")
        for bundle in ("Simplicity", "Structure", "Process"):
            self.assertIn(bundle, q3)

    def test_q4_threshold_has_recommended_75(self):
        q4 = self.text.split("### Question 4")[1].split("## ")[0]
        for label in ("75%", "85%", "50%", "Disabled"):
            self.assertIn(label, q4)
        self.assertIn("recommended", q4.lower())

    def test_question_blocks_within_4_option_ceiling(self):
        """Every fenced question block must declare ≤4 options
        (AskUserQuestion contract)."""
        # Extract each ``` block under a ### Question heading
        sections = re.split(r"### Question \d+", self.text)[1:5]
        for i, sec in enumerate(sections, start=1):
            m = re.search(r"```\n(.*?)```", sec, re.DOTALL)
            if not m:
                continue
            block = m.group(1)
            labels = re.findall(r'^\s*-\s*label:', block, re.MULTILINE)
            self.assertLessEqual(
                len(labels), 4,
                f"Q{i} declares {len(labels)} options; ceiling is 4",
            )


class TestArgAssembly(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_arg_assembly_section_present(self):
        self.assertIn("Arg assembly", self.text)

    def test_assembled_command_uses_kaizen_workflow_config(self):
        self.assertIn("kaizen-workflow-config set", self.text)

    def test_assembled_flags_documented(self):
        for flag in ("--scope", "--run-mode", "--disciplines",
                      "--threshold", "--loop-its", "--loop-stop",
                      "--routine", "--schema"):
            self.assertIn(flag, self.text, f"arg-assembly missing flag: {flag}")

    def test_bundle_expansion_table_present(self):
        """Q3 picks 3 bundles; arg-assembly documents the expansion to
        individual discipline tags."""
        for tag in ("kiss,yagni,dry", "tdd,boy-scout"):
            self.assertIn(tag, self.text,
                           f"bundle expansion missing tag list: {tag}")


class TestRelationshipToSessionMode(unittest.TestCase):
    """The body must explicitly document how /kaizen:workflow relates
    to /kaizen:session-mode so future readers don't merge them."""

    def setUp(self):
        self.text = _CMD.read_text()

    def test_session_mode_section_present(self):
        self.assertRegex(self.text, r"##\s+Relationship to.*session-mode")

    def test_distinguishes_session_vs_persistent(self):
        sec = self.text.split("## Relationship to /kaizen:session-mode")[1]
        self.assertIn("session", sec.lower())
        self.assertRegex(sec.lower(), r"persist|across sessions|durable")


class TestSubcommandsDocumented(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_subcommands_table_lists_all_5(self):
        for sub in ("set", "get", "show", "path", "reset"):
            self.assertIn(f"/kaizen:workflow {sub}", self.text)


class TestPluginManifestPermissions(unittest.TestCase):
    """plugin.json must permit the backing bin + script (iron law:
    plugin-manifest-permissions)."""

    def setUp(self):
        self.manifest = (
            _KZ_DIR / ".claude-plugin/plugin.json"
        ).read_text()

    def test_bin_permitted(self):
        self.assertIn("kaizen-workflow-config", self.manifest)

    def test_script_permitted(self):
        self.assertIn("workflow_config.py", self.manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
