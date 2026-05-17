"""Contract tests for /kaizen:setup super-menu QA pattern.

Pins the AskUserQuestion-driven branched flow added in P1 of the
menu-consolidation plan (commands/setup.md). If the structure drifts
(questions missing, branches missing, arg-mapping wrong, allowed-tools
missing AskUserQuestion), this test fires.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/setup.md"


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()
        self.fm = _frontmatter(self.text)

    def test_setup_command_present(self):
        self.assertTrue(_CMD.is_file())

    def test_name_is_setup(self):
        self.assertIn("name: setup", self.fm)

    def test_allowed_tools_includes_AskUserQuestion(self):
        self.assertIn("AskUserQuestion", self.fm,
                       "menu requires AskUserQuestion in allowed-tools")

    def test_allowed_tools_includes_setup_sh_dispatch(self):
        self.assertIn("setup.sh", self.fm,
                       "args-mode dispatch must stay permitted")

    def test_allowed_tools_includes_detect_stack(self):
        """Default mode needs detect-stack to synthesize add-on flags."""
        self.assertTrue(
            "detect_stack.py" in self.fm or "kaizen-detect-stack" in self.fm,
            "Default install branch needs detect-stack tool permission",
        )

    def test_description_mentions_super_menu(self):
        self.assertIn("super-menu", self.fm.lower())

    def test_argument_hint_documents_empty_means_menu(self):
        self.assertIn("empty", self.fm.lower())
        self.assertIn("menu", self.fm.lower())


class TestMasterPicker(unittest.TestCase):
    """Q1 — top-level master action picker (4 options, per 4-option ceiling)."""

    def setUp(self):
        self.text = _CMD.read_text()

    def test_q1_present(self):
        self.assertRegex(self.text, r"### Question 1 .*master action")

    def test_q1_has_4_master_actions(self):
        """Q1 has exactly the 4 master buckets — branched flows
        live in follow-up questions."""
        q1 = self.text.split("### Question 1")[1].split("### Question 2")[0]
        for label in ("Install / re-install", "Uninstall",
                      "Health check", "Maintenance"):
            self.assertIn(label, q1, f"Q1 missing master action: {label}")

    def test_q1_options_within_4_option_ceiling(self):
        """Per AskUserQuestion contract: ≤4 options per question."""
        q1 = self.text.split("### Question 1")[1].split("### Question 2")[0]
        # Count `- label:` entries inside the fenced block
        labels = re.findall(r'^\s*-\s*label:', q1, re.MULTILINE)
        self.assertLessEqual(len(labels), 4,
                              f"Q1 has {len(labels)} options; ceiling is 4")


class TestInstallBranch(unittest.TestCase):
    """Q2 (install-mode picker) routes to Default/Custom/Reconfigure/Cache."""

    def setUp(self):
        self.text = _CMD.read_text()

    def test_q2_install_mode_picker_present(self):
        self.assertRegex(self.text, r"### Question 2 .*install")

    def test_q2_has_4_install_modes(self):
        q2 = self.text.split("### Question 2")[1].split("### Question 3")[0]
        for label in ("Default", "Custom", "Reconfigure", "Cache stats"):
            self.assertIn(label, q2, f"Q2 (install mode) missing: {label}")

    def test_default_mode_uses_detect_stack(self):
        """The Default branch must reference detect-stack as the
        signal source for add-on flag synthesis."""
        self.assertIn("detect-stack", self.text.lower())
        self.assertRegex(self.text, r"stack-context\.md|detect_stack\.py")

    def test_signal_to_flag_table_present(self):
        """Default-mode flag synthesis is a documented mapping table
        (signal → --with-* flag) the agent reads at runtime."""
        for token in ("Cargo.toml", "--with-index", "Dockerfile",
                       "--with-daemon", "--with-browser"):
            self.assertIn(token, self.text,
                           f"Default-mode mapping table missing: {token}")


class TestCustomWizard(unittest.TestCase):
    """Q3 (scope), Q4 (add-ons), Q5 (dry-run) — the existing wizard
    chain now lives inside the Custom / Reconfigure branch."""

    def setUp(self):
        self.text = _CMD.read_text()

    def test_q3_scope_options_present(self):
        for label in ("Project only", "Project + global stack", "Globals only"):
            self.assertIn(label, self.text)

    def test_q4_addons_uses_multiselect(self):
        q4 = self.text.split("### Question 4")[1].split("### Question 5")[0]
        self.assertIn("multiSelect: true", q4,
                       "Q4 (Add-ons) must be multiSelect: true")

    def test_q5_dry_run_options_present(self):
        for label in ("Yes (recommended)", "No — apply now"):
            self.assertIn(label, self.text)


class TestMaintenanceBranch(unittest.TestCase):
    """Q6 — maintenance op picker (4 ops, dispatches to sibling slashes)."""

    def setUp(self):
        self.text = _CMD.read_text()

    def test_q6_maintenance_present(self):
        self.assertRegex(self.text, r"### Question 6 .*maintenance")

    def test_q6_has_4_maintenance_ops(self):
        q6 = self.text.split("### Question 6")[1].split("### Question 7")[0]
        for label in ("Hygiene", "Update", "Backup", "Cache CRUD"):
            self.assertIn(label, q6, f"Q6 missing maintenance op: {label}")

    def test_maintenance_dispatches_sibling_slashes(self):
        """Maintenance ops dispatch existing first-class slashes
        rather than wrapping them in setup.sh."""
        for slash in ("/kaizen:hygiene", "/kaizen:update",
                      "/kaizen:backup"):
            self.assertIn(slash, self.text,
                           f"Maintenance dispatch missing: {slash}")


class TestUninstallBranch(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_q7_uninstall_dry_run_present(self):
        self.assertRegex(self.text, r"### Question 7 .*uninstall")


class TestArgAssembly(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text()

    def test_arg_assembly_table_present(self):
        self.assertIn("Arg assembly", self.text)

    def test_install_flags_documented(self):
        for flag in ("--enable-all", "--with-index", "--with-browser",
                      "--with-daemon", "--with-trace-proxy", "--dry-run"):
            self.assertIn(flag, self.text, f"arg-assembly missing flag: {flag}")

    def test_per_branch_assembly_documented(self):
        """Each Q1 branch maps to a base command — picker → outcome
        deterministically."""
        for branch in ("Install", "Uninstall", "Health check", "Maintenance"):
            self.assertIn(branch, self.text)


class TestReconfigureSemantics(unittest.TestCase):
    """Reconfigure is not a new subcommand — it's documented as
    `install`-rerun semantics. Confirms the design decision survives
    future churn."""

    def setUp(self):
        self.text = _CMD.read_text()

    def test_reconfigure_section_present(self):
        self.assertRegex(self.text, r"##\s+Reconfigure semantics")

    def test_reconfigure_uses_install_idempotently(self):
        rec = self.text.split("## Reconfigure semantics")[1].split("##")[0]
        self.assertRegex(rec.lower(), r"idempotent|re-?run.*install")


class TestBackcompat(unittest.TestCase):
    """Args-mode dispatch must still work — args-mode is the canonical
    CLI for scripts/CI; menu is for humans."""

    def test_setup_sh_exec_block_present(self):
        text = _CMD.read_text()
        self.assertIn("setup.sh $ARGUMENTS", text,
                       "args-mode dispatch (top-of-file ! block) must remain")

    def test_existing_subcommands_still_documented(self):
        text = _CMD.read_text()
        for sub in ("install", "uninstall", "cache"):
            self.assertIn(f"/kaizen:setup {sub}", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
