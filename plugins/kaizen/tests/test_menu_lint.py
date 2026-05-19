"""TDD — menu_lint.py — verify menu slash commands declare
AskUserQuestion + respect the 4-Q × 4-option AskUserQuestion contract.

Menu-consolidation P7. Pure function `lint_menu(text, path) -> list[dict]`
returns findings; CLI emits a summary. Non-menu commands (no
AskUserQuestion in body) are skipped silently.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/quality/menu_lint.py"


def _load():
    spec = importlib.util.spec_from_file_location("ml", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ml"] = mod
    spec.loader.exec_module(mod)
    return mod


def _menu_md(*, allowed_tools: str, questions: int = 1,
               options_per_q: int = 3, body_extra: str = "") -> str:
    """Build a synthetic menu slash-command body for tests."""
    fm = (
        "---\n"
        "name: test-menu\n"
        'description: "Test menu. Triggers on \\"foo\\", \\"bar\\", \\"baz\\"."\n'
        f"allowed-tools: {allowed_tools}\n"
        "---\n\n"
        "# /kaizen:test-menu\n\n"
        "## Interactive wizard\n\n"
    )
    body_qs = []
    for i in range(1, questions + 1):
        opt_block = "\n".join(
            f'  - label: "opt-{j}"\n    description: "..."'
            for j in range(1, options_per_q + 1)
        )
        body_qs.append(
            f"### Question {i}\n\n"
            "```\n"
            f"question:    \"q{i}?\"\n"
            "multiSelect: false\n"
            "options:\n"
            f"{opt_block}\n"
            "```\n"
        )
    return fm + "\n".join(body_qs) + body_extra


def _non_menu_md() -> str:
    """Synthetic NON-menu slash command (no AskUserQuestion at all)."""
    return (
        "---\n"
        "name: plain\n"
        'description: "Plain command. Triggers on \\"a\\", \\"b\\", \\"c\\"."\n'
        "---\n\n"
        "# /kaizen:plain\n\n"
        "Static body, no wizard.\n"
        "!`echo hello`\n"
    )


class TestLintMenu(unittest.TestCase):
    def setUp(self):
        self.ml = _load()

    def test_clean_menu_returns_no_findings(self):
        text = _menu_md(
            allowed_tools='["AskUserQuestion", "Bash(echo:*)"]',
            questions=2, options_per_q=3,
        )
        findings = self.ml.lint_menu(text, "test.md")
        self.assertEqual(findings, [])

    def test_missing_askuserquestion_in_allowed_tools_flags(self):
        text = _menu_md(
            allowed_tools='["Bash(echo:*)"]',
            questions=2, options_per_q=3,
        )
        findings = self.ml.lint_menu(text, "test.md")
        self.assertGreaterEqual(len(findings), 1)
        kinds = [f["rule_id"] for f in findings]
        self.assertIn("missing-askuserquestion-perm", kinds)

    def test_too_many_options_flags(self):
        """AskUserQuestion contract: max 4 options per question."""
        text = _menu_md(
            allowed_tools='["AskUserQuestion"]',
            questions=1, options_per_q=6,
        )
        findings = self.ml.lint_menu(text, "test.md")
        kinds = [f["rule_id"] for f in findings]
        self.assertIn("too-many-options", kinds)

    def test_too_many_questions_flags(self):
        """AskUserQuestion contract: max 4 questions PER CALL (per fenced
        block). 5 questions in one fence → flagged."""
        single_fence_5q = (
            "---\n"
            "name: test-menu\n"
            'description: "x. Triggers on \\"a\\", \\"b\\", \\"c\\"."\n'
            'allowed-tools: ["AskUserQuestion"]\n'
            "---\n\n"
            "## Wizard\n\n```\n"
            + "\n".join(
                f"question:    \"q{i}?\"\noptions:\n"
                "  - label: \"a\"\n    description: \"...\"\n"
                "  - label: \"b\"\n    description: \"...\"\n"
                for i in range(1, 6)
            )
            + "\n```\n"
        )
        findings = self.ml.lint_menu(single_fence_5q, "test.md")
        kinds = [f["rule_id"] for f in findings]
        self.assertIn("too-many-questions", kinds)

    def test_multi_fence_multi_question_clean(self):
        """A menu making multiple SEPARATE AskUserQuestion calls (each
        in its own fence) does NOT count as one big call. setup.md
        shape — multiple sequential picks is the canonical pattern."""
        # 5 questions across 5 fences → 1 question per call → clean
        text = _menu_md(
            allowed_tools='["AskUserQuestion"]',
            questions=5, options_per_q=3,
        )
        findings = self.ml.lint_menu(text, "test.md")
        kinds = [f["rule_id"] for f in findings]
        self.assertNotIn("too-many-questions", kinds)

    def test_non_menu_command_no_findings(self):
        """Files without AskUserQuestion in body or frontmatter are
        skipped silently — not every slash is a menu."""
        text = _non_menu_md()
        findings = self.ml.lint_menu(text, "test.md")
        self.assertEqual(findings, [])

    def test_finding_includes_path_and_severity(self):
        text = _menu_md(allowed_tools='["Bash(echo:*)"]')
        findings = self.ml.lint_menu(text, "/some/path/test.md")
        self.assertGreaterEqual(len(findings), 1)
        f = findings[0]
        self.assertIn("severity", f)
        self.assertIn("rule_id", f)
        self.assertIn("path", f)
        self.assertEqual(f["path"], "/some/path/test.md")


class TestCli(unittest.TestCase):
    def setUp(self):
        self.ml = _load()

    def test_scan_clean_dir_exits_zero(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            cmds = Path(tmp) / "commands"
            cmds.mkdir()
            (cmds / "clean.md").write_text(_menu_md(
                allowed_tools='["AskUserQuestion"]', questions=2, options_per_q=4))
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT), "check", "--commands-dir", str(cmds)],
                capture_output=True, text=True, timeout=10,
            )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_scan_dirty_dir_exits_nonzero(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            cmds = Path(tmp) / "commands"
            cmds.mkdir()
            (cmds / "broken.md").write_text(_menu_md(
                allowed_tools='["Bash(echo:*)"]',  # missing AskUserQuestion
                questions=2, options_per_q=3))
            proc = subprocess.run(
                [sys.executable, str(_SCRIPT), "check", "--commands-dir", str(cmds)],
                capture_output=True, text=True, timeout=10,
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing-askuserquestion-perm", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
