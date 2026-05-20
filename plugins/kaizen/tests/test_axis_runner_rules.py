"""axis-runner pure-fn rules (#161): grep / ast-rule / file-coverage.

C3 covers the three dispatcher backends in isolation — composable
inward-pointing units (per onion-DDD), each testable without YAML or
envelope wrapping.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

class TestRunGrep(unittest.TestCase):
    def test_grep_finds_pattern(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("hello\nTODO: fix\nbye\n")
            (root / "b.md").write_text("clean\n")
            findings = rules.run_grep("TODO", "*.md", root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["path"], "a.md")
            self.assertEqual(findings[0]["line"], 2)
            self.assertEqual(findings[0]["match"], "TODO")

    def test_grep_recursive_glob(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "sub" / "deep.md").write_text("trailing  \nok\n")
            findings = rules.run_grep(r" +$", "**/*.md", root)
            self.assertEqual(len(findings), 1)
            self.assertIn("deep.md", findings[0]["path"])

    def test_grep_no_matches_empty(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("clean\n")
            self.assertEqual(rules.run_grep("MISSING", "*.md", root), [])

class TestRunAstRule(unittest.TestCase):
    def test_class_camelcase_flags_lowercase(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.py").write_text(
                "class badname:\n    pass\nclass GoodName:\n    pass\n"
            )
            findings = rules.run_ast_rule("class-camelcase", "*.py", root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["name"], "badname")
            self.assertEqual(findings[0]["rule"], "class-camelcase")

    def test_subprocess_rc_flags_ignored(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.py").write_text(textwrap.dedent("""
                import subprocess
                subprocess.run(["ls"])
                r = subprocess.run(["ls"])
                subprocess.run(["ls"], check=True)
            """).lstrip())
            findings = rules.run_ast_rule(
                "subprocess-rc-check", "*.py", root
            )
            # Only the bare-Expr subprocess.run without check=True
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["call"], "run")

    def test_unknown_rule_raises(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                rules.run_ast_rule("nonexistent-rule", "*.py", Path(tmp))

class TestRunFileCoverage(unittest.TestCase):
    def test_missing_counterpart_flagged(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "alpha.py").write_text("")
            (root / "src" / "beta.py").write_text("")
            (root / "tests" / "test_alpha.py").write_text("")
            # no test_beta.py → beta.py should be flagged
            findings = rules.run_file_coverage(
                "src/*.py", "tests/test_*.py", root
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("beta.py", findings[0]["path"])

    def test_full_coverage_returns_empty(self):
        import axis_runner_rules as rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "alpha.py").write_text("")
            (root / "tests" / "test_alpha.py").write_text("")
            self.assertEqual(rules.run_file_coverage(
                "src/*.py", "tests/test_*.py", root
            ), [])

if __name__ == "__main__":
    unittest.main()
