"""Tests for _summary.py — O5 smart file-level summary.

The Python summarizer uses stdlib ``ast`` so all those tests run in
every CI env. The tree-sitter path is exercised when the wheel is
installed; otherwise it falls through to the legacy snippet fallback
(also tested).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _summary  # noqa: E402

class TestPythonSummary(unittest.TestCase):
    def test_extracts_signatures(self):
        source = """\
import os
import sys

def alpha(x: int) -> str:
    \"\"\"First line of alpha.

    More body here.
    \"\"\"
    return str(x)

def beta(y):
    return y + 1

class Thing:
    \"\"\"A thing.\"\"\"
    def method(self, a):
        pass
"""
        out = _summary._python_summary(source, max_chars=2048)
        self.assertIn("imports: os, sys", out)
        self.assertIn("def alpha(x: int) -> str:", out)
        self.assertIn('"""First line of alpha."""', out)
        self.assertIn("def beta(y):", out)
        self.assertIn("class Thing:", out)
        self.assertIn('"""A thing."""', out)
        self.assertIn("def method(self, a):", out)

    def test_async_function(self):
        out = _summary._python_summary(
            "async def foo(x: int) -> int:\n    return x\n",
            max_chars=2048,
        )
        self.assertIn("async def foo(x: int) -> int:", out)

    def test_class_with_bases(self):
        out = _summary._python_summary(
            "class Child(Parent, Mixin):\n    pass\n",
            max_chars=2048,
        )
        self.assertIn("class Child(Parent, Mixin):", out)

    def test_module_docstring(self):
        out = _summary._python_summary(
            '"""Module docstring first line.\n\nMore."""\n\ndef f():\n    pass\n',
            max_chars=2048,
        )
        self.assertIn('"""Module docstring first line."""', out)

    def test_parse_error_returns_empty(self):
        # Syntax-broken source → fall through (caller decides fallback)
        out = _summary._python_summary("def broken(", max_chars=2048)
        self.assertEqual(out, "")

    def test_imports_dedup(self):
        out = _summary._python_summary(
            "import os\nimport os.path\nfrom os import getcwd\nimport sys\n",
            max_chars=2048,
        )
        # "os" should appear once (de-duped); "sys" once
        self.assertEqual(out.count("os, sys"), 1)

    def test_relative_imports_skipped(self):
        out = _summary._python_summary(
            "from . import x\nfrom .. import y\nimport real_module\n",
            max_chars=2048,
        )
        self.assertIn("real_module", out)
        # Relative imports have no module name; shouldn't pollute
        self.assertNotIn("imports: .", out)

    def test_methods_have_no_docstring_in_summary(self):
        source = """\
class C:
    def method(self):
        \"\"\"Method doc.\"\"\"
        pass
"""
        out = _summary._python_summary(source, max_chars=2048)
        self.assertIn("def method(self):", out)
        # The method docstring should NOT appear (budget protection)
        self.assertNotIn("Method doc", out)

    def test_truncates_to_budget(self):
        # Lots of functions to overflow a small budget
        lines = "\n".join(f"def fn_{i}(): pass" for i in range(200))
        out = _summary._python_summary(lines, max_chars=200)
        self.assertLessEqual(len(out), 250)  # budget + small overshoot tolerance

    def test_no_body_no_sigs_returns_minimal(self):
        # Empty source
        out = _summary._python_summary("", max_chars=2048)
        # Either empty or just whitespace/newline
        self.assertEqual(out.strip(), "")

class TestSmartSummaryDispatch(unittest.TestCase):
    """Dispatch logic: python → ast, others → ts, neither → fallback."""

    def test_python_path(self):
        out = _summary.smart_summary(
            "def hello():\n    pass\n",
            "python",
            "fallback text here",
            max_chars=2048,
        )
        self.assertIn("def hello():", out)
        self.assertNotIn("fallback text", out)

    def test_python_parse_error_uses_fallback(self):
        out = _summary.smart_summary(
            "def broken(",  # syntax error
            "python",
            "fallback text here",
            max_chars=2048,
        )
        self.assertIn("fallback text", out)

    def test_unknown_language_uses_fallback(self):
        out = _summary.smart_summary(
            "some content",
            "brainfuck",
            "fallback content",
            max_chars=2048,
        )
        # No ts grammar for brainfuck → fallback
        self.assertEqual(out, "fallback content")

    def test_empty_source_returns_fallback(self):
        out = _summary.smart_summary(
            "", "python", "fb", max_chars=2048,
        )
        self.assertEqual(out, "fb")

    def test_empty_source_and_no_fallback_returns_empty(self):
        out = _summary.smart_summary(
            "", "python", "", max_chars=2048,
        )
        self.assertEqual(out, "")

    def test_max_chars_respected_on_fallback(self):
        out = _summary.smart_summary(
            "", "?", "x" * 5000, max_chars=100,
        )
        self.assertEqual(len(out), 100)

    def test_no_language_uses_fallback(self):
        # Edge case: language is empty/None
        out = _summary.smart_summary(
            "some text", "", "fb", max_chars=2048,
        )
        self.assertEqual(out, "fb")

@unittest.skipUnless(
    True,  # Import works regardless of ts presence; smart_summary handles None
    "always runs — _ts_summary handles missing ts internally",
)
class TestTreeSitterSummary(unittest.TestCase):
    def test_ts_summary_returns_string_or_empty(self):
        # When tree-sitter is missing, returns "". Either way must be str.
        out = _summary._ts_summary("fn hello() {}", "rust", 2048)
        self.assertIsInstance(out, str)

class TestSignatureHelpers(unittest.TestCase):
    def test_first_docstring_line_strips_whitespace(self):
        import ast
        tree = ast.parse('def f():\n    """  \n  Hello world\n  More\n  """\n    pass\n')
        node = tree.body[0]
        self.assertEqual(_summary._first_docstring_line(node), "Hello world")

    def test_first_docstring_line_none_when_no_docstring(self):
        import ast
        tree = ast.parse("def f():\n    pass\n")
        node = tree.body[0]
        self.assertEqual(_summary._first_docstring_line(node), "")

    def test_python_signature_function(self):
        import ast
        tree = ast.parse("def foo(x: int, y: str = 'a') -> bool:\n    pass\n")
        sig = _summary._python_signature(tree.body[0])
        self.assertIn("def foo(", sig)
        self.assertIn("-> bool:", sig)

    def test_python_signature_class(self):
        import ast
        tree = ast.parse("class C(A, B):\n    pass\n")
        sig = _summary._python_signature(tree.body[0])
        self.assertEqual(sig, "class C(A, B):")

    def test_python_signature_unsupported_node_returns_empty(self):
        import ast
        tree = ast.parse("x = 1\n")
        sig = _summary._python_signature(tree.body[0])
        self.assertEqual(sig, "")

if __name__ == "__main__":
    unittest.main()
