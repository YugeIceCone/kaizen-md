"""Tests for O2 (minimal) — AST-aware Python chunking.

Run:
    python3 -m unittest tests.test_ast_chunk -v
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _ast_chunk as ac  # noqa: E402

def _src(body: str) -> str:
    return textwrap.dedent(body).lstrip("\n")

class TestChunkPythonBySymbol(unittest.TestCase):
    def test_returns_empty_on_syntax_error(self):
        self.assertEqual(ac.chunk_python_by_symbol("def broken("), [])

    def test_single_function_is_one_chunk(self):
        src = _src("""
            def foo():
                return 1
        """)
        chunks = ac.chunk_python_by_symbol(src)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].kind, "function")
        self.assertEqual(chunks[0].symbol_name, "foo")
        self.assertIn("return 1", chunks[0].text)

    def test_module_prologue_emitted_first(self):
        src = _src("""
            import os
            import sys

            CONST = 42

            def foo():
                pass
        """)
        chunks = ac.chunk_python_by_symbol(src)
        self.assertEqual(chunks[0].kind, "module")
        self.assertIn("import os", chunks[0].text)
        self.assertIn("CONST", chunks[0].text)
        self.assertEqual(chunks[1].kind, "function")

    def test_no_prologue_when_file_starts_with_def(self):
        src = _src("""
            def foo():
                pass
        """)
        chunks = ac.chunk_python_by_symbol(src)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].kind, "function")

    def test_class_under_max_chars_is_one_chunk(self):
        src = _src("""
            class Foo:
                def bar(self):
                    return 1
        """)
        chunks = ac.chunk_python_by_symbol(src, max_chars=2000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].kind, "class")
        self.assertEqual(chunks[0].symbol_name, "Foo")

    def test_class_over_max_splits_per_method(self):
        # 5 small methods → each ~30 chars → class total < 2000 but force
        # split with max_chars=50.
        src = _src("""
            class Big:
                def a(self):
                    pass
                def b(self):
                    pass
                def c(self):
                    pass
        """)
        chunks = ac.chunk_python_by_symbol(src, max_chars=50)
        self.assertGreaterEqual(len(chunks), 2)
        kinds = [c.kind for c in chunks]
        self.assertIn("class", kinds)  # header chunk
        self.assertIn("method", kinds)  # at least one method chunk
        # Methods carry parent.name qualification
        methods = [c for c in chunks if c.kind == "method"]
        for m in methods:
            self.assertTrue(m.symbol_name.startswith("Big."))

    def test_async_function_kind(self):
        src = _src("""
            async def task():
                return 1
        """)
        chunks = ac.chunk_python_by_symbol(src)
        self.assertEqual(chunks[0].kind, "async-function")

    def test_top_level_statement_becomes_block_chunk(self):
        src = _src("""
            def foo():
                pass

            x = 42
        """)
        chunks = ac.chunk_python_by_symbol(src)
        kinds = [c.kind for c in chunks]
        self.assertIn("function", kinds)
        self.assertIn("block", kinds)

    def test_chunk_idx_is_sequential_unique(self):
        src = _src("""
            import os

            def a(): pass
            def b(): pass
            def c(): pass
        """)
        chunks = ac.chunk_python_by_symbol(src)
        indices = [c.chunk_idx for c in chunks]
        self.assertEqual(indices, list(range(len(chunks))))

class TestExtractImports(unittest.TestCase):
    def test_plain_import(self):
        out = ac.extract_python_imports("import os\nimport sys\n")
        self.assertEqual([(r.symbol, r.module) for r in out],
                         [("os", "os"), ("sys", "sys")])

    def test_from_import(self):
        out = ac.extract_python_imports("from pathlib import Path\n")
        self.assertEqual(out[0].symbol, "Path")
        self.assertEqual(out[0].module, "pathlib")

    def test_aliased_import(self):
        out = ac.extract_python_imports("import numpy as np\n")
        self.assertEqual(out[0].symbol, "np")
        self.assertEqual(out[0].module, "numpy")

    def test_multiple_from_imports(self):
        out = ac.extract_python_imports(
            "from os.path import join, basename\n"
        )
        symbols = {r.symbol for r in out}
        self.assertEqual(symbols, {"join", "basename"})
        for r in out:
            self.assertEqual(r.module, "os.path")

    def test_syntax_error_returns_empty(self):
        self.assertEqual(ac.extract_python_imports("def broken("), [])

if __name__ == "__main__":
    unittest.main()
