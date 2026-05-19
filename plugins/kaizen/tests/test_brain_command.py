"""Contract tests for /kaizen:brain empty-args multiSelect verb checklist
(P4 of the menu-consolidation plan). Pins the menu structure + the
dispatch table + that args-mode still works for the curated-out verbs.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_CMD = _KZ_DIR / "commands/brain.md"


def _fm(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")
        self.fm = _fm(self.text)

    def test_brain_command_present(self):
        self.assertTrue(_CMD.is_file())

    def test_name_is_brain(self):
        self.assertIn("name: brain", self.fm)

    def test_allowed_tools_includes_AskUserQuestion(self):
        self.assertIn("AskUserQuestion", self.fm)

    def test_allowed_tools_includes_brain_backing_scripts(self):
        """allowed-tools must permit each backing script the dispatcher
        execs (brain.py / build_index.py / brain_promote.py /
        brain_audit.py / brain_evolve.py)."""
        for script in ("brain.py", "build_index.py", "brain_promote.py",
                        "brain_audit.py", "brain_evolve.py"):
            self.assertIn(script, self.fm,
                           f"allowed-tools missing backing script: {script}")

    def test_argument_hint_documents_empty_means_checklist(self):
        self.assertIn("empty", self.fm.lower())
        self.assertRegex(self.fm.lower(), r"multiselect|checklist")

    def test_description_mentions_no_args_menu(self):
        self.assertRegex(self.fm.lower(), r"no-args|multi[Ss]elect.*verb")


class TestMenuStructure(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_menu_section_present(self):
        self.assertRegex(self.text, r"##\s+Interactive menu")

    def test_question_is_multiselect(self):
        # The fenced block under "### Question — verb picker"
        sec = self.text.split("### Question — verb picker")[1]
        m = re.search(r"```\n(.*?)```", sec, re.DOTALL)
        self.assertIsNotNone(m)
        block = m.group(1)
        self.assertIn("multiSelect: true", block,
                       "verb checklist must be multiSelect")

    def test_4_high_frequency_verbs_offered(self):
        for label in ("Capture", "Search", "Audit", "Status"):
            self.assertIn(f'"{label}"', self.text,
                           f"verb checklist missing high-freq verb: {label}")

    def test_picker_respects_4_option_ceiling(self):
        sec = self.text.split("### Question — verb picker")[1]
        m = re.search(r"```\n(.*?)```", sec, re.DOTALL)
        block = m.group(1) if m else ""
        labels = re.findall(r'^\s*-\s*label:', block, re.MULTILINE)
        self.assertLessEqual(len(labels), 4,
                              f"verb picker has {len(labels)} options; "
                              "ceiling is 4 — extend via multi-call "
                              "drill-down if more are needed")


class TestDispatchTable(unittest.TestCase):
    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_dispatch_table_present(self):
        self.assertRegex(self.text, r"###\s+After the pick")

    def test_each_picker_verb_has_dispatch_row(self):
        for verb, slash in (("Capture", "/kaizen:brain capture"),
                             ("Search", "/kaizen:brain search"),
                             ("Audit", "/kaizen:brain audit"),
                             ("Status", "/kaizen:brain status")):
            self.assertIn(verb, self.text)
            self.assertIn(slash, self.text,
                           f"dispatch table missing slash for {verb}")

    def test_curated_out_verbs_documented_as_args_mode(self):
        """The verbs not in the picker (detect/path/promote/evolve/etc.)
        must still be reachable; the body documents how."""
        sec = self.text.split("### After the pick")[1].split("## ")[0]
        for verb in ("detect", "path", "promote", "evolve"):
            self.assertIn(verb, sec,
                           f"curated-out verb not documented: {verb}")


class TestArgsModeBackcompat(unittest.TestCase):
    """The pre-P4 args-mode bash dispatcher MUST still work and route
    every existing verb to its backing script."""

    def setUp(self):
        self.text = _CMD.read_text(encoding="utf-8")

    def test_args_mode_section_present(self):
        self.assertRegex(self.text, r"##\s+Args-mode dispatch")

    def test_dispatcher_routes_capture_to_brain_py(self):
        # Dispatcher case-block + brain.py exec target both present
        # in the args-mode section (DOTALL because the case is split
        # across multiple lines).
        self.assertRegex(self.text, r"(?s)capture\|.*brain\.py")

    def test_dispatcher_routes_search_to_build_index_py(self):
        self.assertIn("search", self.text)
        self.assertIn("build_index.py", self.text)

    def test_dispatcher_routes_promote_to_brain_promote_py(self):
        self.assertIn("brain_promote.py", self.text)

    def test_dispatcher_routes_audit_to_brain_audit_py(self):
        self.assertIn("brain_audit.py", self.text)

    def test_dispatcher_routes_evolve_to_brain_evolve_py(self):
        self.assertIn("brain_evolve.py", self.text)

    def test_empty_args_default_is_status(self):
        """Pre-P4 default — when $ARGUMENTS empty and dispatch fires
        through, ARGS defaults to 'status'. Preserved as a back-compat
        safety net for scripts/CI that invoke the args-mode body
        directly."""
        self.assertIn('ARGS="${ARGUMENTS:-status}"', self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
