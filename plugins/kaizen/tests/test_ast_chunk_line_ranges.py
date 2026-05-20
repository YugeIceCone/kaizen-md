"""Phase 1: SymbolChunk carries line_start + line_end (1-indexed, inclusive).

ast.AST nodes already expose lineno + end_lineno — just wire them
through to the SymbolChunk dataclass. Backward-compatible default=0
so existing consumers stay green.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
_SAMPLE = '''"""module docstring"""

import os

CONST = 1

def foo(x):
    return x + 1

class Bar:
    def method(self):
        return self
'''

class TestSymbolChunkHasLineFields(unittest.TestCase):

    def test_dataclass_has_line_start_line_end_fields(self):
        import _ast_chunk as ac
        sc = ac.SymbolChunk(
            text="x", char_start=0, char_end=1,
            chunk_idx=0, symbol_name="x", kind="function",
            line_start=10, line_end=20,
        )
        self.assertEqual(sc.line_start, 10)
        self.assertEqual(sc.line_end, 20)

    def test_default_values_are_zero(self):
        """Backward-compat: callers that don't pass the new fields work."""
        import _ast_chunk as ac
        sc = ac.SymbolChunk(
            text="x", char_start=0, char_end=1,
            chunk_idx=0, symbol_name="x", kind="function",
        )
        self.assertEqual(sc.line_start, 0)
        self.assertEqual(sc.line_end, 0)

class TestLineRangesPopulated(unittest.TestCase):

    def test_module_prologue_has_line_range(self):
        import _ast_chunk as ac
        chunks = ac.chunk_python_by_symbol(_SAMPLE)
        prologue = next(c for c in chunks if c.kind == "module")
        self.assertEqual(prologue.line_start, 1)
        # Prologue ends at the last line before `def foo` (line 8)
        self.assertGreaterEqual(prologue.line_end, 5)
        self.assertLess(prologue.line_end, 8)

    def test_function_line_range(self):
        import _ast_chunk as ac
        chunks = ac.chunk_python_by_symbol(_SAMPLE)
        foo = next(c for c in chunks if c.symbol_name == "foo")
        self.assertEqual(foo.line_start, 8)
        self.assertEqual(foo.line_end, 9)

    def test_class_line_range_when_not_split(self):
        """For a small class, the whole class is one chunk."""
        import _ast_chunk as ac
        chunks = ac.chunk_python_by_symbol(_SAMPLE)
        # Find a chunk owning Bar (may be 'Bar' or split into header+method)
        bar_chunks = [c for c in chunks
                      if c.symbol_name in ("Bar", "method", "Bar.method")]
        self.assertTrue(bar_chunks, "expected at least one Bar-related chunk")
        for c in bar_chunks:
            self.assertGreaterEqual(c.line_start, 12)
            self.assertLessEqual(c.line_end, 14)

if __name__ == "__main__":
    unittest.main()
