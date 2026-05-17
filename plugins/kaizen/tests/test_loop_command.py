"""Tests for /kaizen:loop slash command — auto-honor session-mode."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/loop.md"


class TestSessionModeAutoHonor(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_command_file_exists(self):
        self.assertTrue(_CMD.is_file())

    def test_body_mentions_auto_honor_section(self):
        """Body must instruct agent to read session-mode before composing."""
        self.assertIn("Auto-honor session-mode", self.text)
        self.assertIn("kaizen-session-mode get", self.text)

    def test_body_handles_mode_loop_case(self):
        self.assertIn('mode == "loop"', self.text)
        self.assertIn("pinned disciplines", self.text)

    def test_body_handles_mode_workflow_or_neither_case(self):
        self.assertIn('mode == "workflow"', self.text)
        self.assertIn('"neither"', self.text)
        self.assertIn("Confirm with the user", self.text)

    def test_body_handles_no_session_mode_case(self):
        self.assertIn("no session-mode is set", self.text)

    def test_body_references_threshold_handoff_contract(self):
        """Body should note that --threshold fires independently."""
        self.assertIn("--threshold", self.text)
        self.assertIn("auto-handoff", self.text.lower())

    def test_allowed_tools_includes_session_mode_bin(self):
        fm = re.match(r"^---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(fm)
        self.assertIn("kaizen-session-mode", fm.group(1))


# ─── P3 super-menu wizard contract ───────────────────────────────────


def _fm(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


class TestP3WizardFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")
        self.fm = _fm(self.text)

    def test_allowed_tools_includes_AskUserQuestion(self):
        self.assertIn("AskUserQuestion", self.fm,
                       "P3 wizard requires AskUserQuestion permission")

    def test_allowed_tools_includes_workflow_config(self):
        """The /kaizen:workflow Q2=Loop bridge needs to persist via
        kaizen-workflow-config — permission must be declared."""
        self.assertIn("kaizen-workflow-config", self.fm)

    def test_argument_hint_documents_empty_means_wizard(self):
        self.assertIn("empty", self.fm.lower())
        self.assertRegex(self.fm, r"2-Q|wizard")

    def test_description_mentions_2q_wizard(self):
        self.assertIn("2-question", self.fm.lower())


class TestP3WizardStructure(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_wizard_section_present(self):
        self.assertRegex(self.text, r"##\s+Interactive wizard")

    def test_exactly_two_numbered_questions(self):
        qs = re.findall(r"### Question (\d+)", self.text)
        self.assertEqual(sorted(qs), ["1", "2"],
                          f"expected Q1+Q2 only; got {qs}")

    def test_q1_budget_options_include_recommended_30(self):
        q1 = self.text.split("### Question 1")[1].split("### Question 2")[0]
        for label in ("10", "20", "30", "60"):
            self.assertIn(label, q1, f"Q1 missing budget option: {label}")
        self.assertIn("recommended", q1.lower())

    def test_q1_within_4_option_ceiling(self):
        q1 = self.text.split("### Question 1")[1].split("### Question 2")[0]
        m = re.search(r"```\n(.*?)```", q1, re.DOTALL)
        block = m.group(1) if m else ""
        labels = re.findall(r'^\s*-\s*label:', block, re.MULTILINE)
        self.assertLessEqual(
            len(labels), 4,
            f"Q1 has {len(labels)} options; ceiling is 4",
        )

    def test_q2_multiselect_with_4_stop_conditions(self):
        q2 = self.text.split("### Question 2")[1].split("### After the 2")[0]
        self.assertIn("multiSelect: true", q2,
                       "Q2 (stop conditions) must be multiSelect: true")
        for label in ("Ledger empty", "Completion promise",
                      "Iteration cap", "Manual cancel"):
            self.assertIn(label, q2, f"Q2 missing stop condition: {label}")


class TestP3BridgeFromWorkflow(unittest.TestCase):
    """The P3 wizard documents its role as the bridge from
    /kaizen:workflow Q2=Loop."""

    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_bridge_documented(self):
        self.assertIn("/kaizen:workflow", self.text)
        self.assertRegex(self.text, r"Q2.*Loop|bridge|workflow-config set")

    def test_persists_via_workflow_config(self):
        """When invoked via workflow Q2=Loop, must persist
        --loop-its and --loop-stop on the workflow-config."""
        self.assertIn("--loop-its", self.text)
        self.assertIn("--loop-stop", self.text)


class TestP3ArgAssembly(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_arg_assembly_table_present(self):
        self.assertIn("Arg assembly", self.text)

    def test_q1_maps_to_its(self):
        for budget in ("--its 10", "--its 20", "--its 30", "--its 60"):
            self.assertIn(budget, self.text,
                           f"Q1 → flag mapping missing: {budget}")

    def test_completion_promise_maps_to_promise_flag(self):
        self.assertIn("--promise", self.text)


class TestP3Backcompat(unittest.TestCase):
    """Pre-P3 args-mode usage MUST still be documented + working."""

    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_usage_section_intact(self):
        self.assertIn("## Usage", self.text)
        self.assertIn("--item", self.text)
        self.assertRegex(self.text, r"<promise>.*</promise>")

    def test_cancel_invocation_intact(self):
        self.assertIn("--cancel", self.text)

    def test_setup_ralph_loop_script_still_wired(self):
        self.assertIn("setup-ralph-loop.sh", self.text)


if __name__ == "__main__":
    unittest.main()
