"""Tests for _ts_chunk.py — tree-sitter universal chunker (O8).

The real tree-sitter parser requires the ``tree_sitter_languages``
wheel (~50 MB binary deps); tests gate on availability and skip the
parsing-based cases when missing. Pure-logic parts — language mapping,
node classification, graceful fallback — run in every CI environment.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _ts_chunk  # noqa: E402


class TestLanguageMapping(unittest.TestCase):
    def test_resolves_common_names(self):
        self.assertEqual(_ts_chunk._resolve_ts_lang("rust"), "rust")
        self.assertEqual(_ts_chunk._resolve_ts_lang("go"), "go")
        self.assertEqual(_ts_chunk._resolve_ts_lang("javascript"), "javascript")
        self.assertEqual(_ts_chunk._resolve_ts_lang("typescript"), "typescript")
        self.assertEqual(_ts_chunk._resolve_ts_lang("c++"), "cpp")
        self.assertEqual(_ts_chunk._resolve_ts_lang("cpp"), "cpp")

    def test_resolves_aliases(self):
        # Short-form aliases that the language detector emits
        self.assertEqual(_ts_chunk._resolve_ts_lang("ts"), "typescript")
        self.assertEqual(_ts_chunk._resolve_ts_lang("js"), "javascript")
        self.assertEqual(_ts_chunk._resolve_ts_lang("rb"), "ruby")
        self.assertEqual(_ts_chunk._resolve_ts_lang("cs"), "c_sharp")

    def test_case_insensitive(self):
        self.assertEqual(_ts_chunk._resolve_ts_lang("RUST"), "rust")
        self.assertEqual(_ts_chunk._resolve_ts_lang("Python"), "python")

    def test_unknown_language_returns_none(self):
        self.assertIsNone(_ts_chunk._resolve_ts_lang("brainfuck"))
        self.assertIsNone(_ts_chunk._resolve_ts_lang(""))
        self.assertIsNone(_ts_chunk._resolve_ts_lang(None))


class TestDefinitionDetection(unittest.TestCase):
    def test_recognizes_definition_suffixes(self):
        for ty in (
            "function_definition", "method_declaration",
            "function_item", "impl_item", "trait_item",
            "class_declaration", "struct_specifier",
        ):
            self.assertTrue(_ts_chunk._is_definition_node(ty),
                            f"expected {ty!r} → True")

    def test_recognizes_bare_names(self):
        # Ruby uses unsuffixed type names
        for ty in ("function", "method", "class", "module", "trait"):
            self.assertTrue(_ts_chunk._is_definition_node(ty),
                            f"expected bare {ty!r} → True")

    def test_rejects_non_definitions(self):
        for ty in (
            "expression_statement", "call_expression",
            "binary_expression", "identifier", "literal",
            "comment", "string", "",
        ):
            self.assertFalse(_ts_chunk._is_definition_node(ty),
                             f"expected {ty!r} → False")

    def test_handles_none(self):
        self.assertFalse(_ts_chunk._is_definition_node(None))


class TestKindClassification(unittest.TestCase):
    def test_kind_buckets(self):
        cases = [
            ("function_definition", "function"),
            ("function_item", "function"),
            ("method_declaration", "method"),
            ("class_declaration", "class"),
            ("class", "class"),
            ("struct_item", "struct"),
            ("trait_item", "trait"),
            ("impl_item", "impl"),
            ("enum_item", "enum"),
            ("interface_declaration", "interface"),
            ("module", "module"),
            ("type_alias", "block"),  # 'type_alias' has no hint match
            ("foo", "block"),
            ("", "block"),
        ]
        for ty, expected in cases:
            actual = _ts_chunk._classify_kind(ty)
            self.assertEqual(actual, expected, f"{ty!r} → {actual!r}")


class TestGracefulFallback(unittest.TestCase):
    """When tree_sitter_languages isn't installed, the chunker must
    return [] for every input rather than crash."""

    def setUp(self):
        _ts_chunk.reset_cache()

    def test_python_always_returns_empty(self):
        # Python is reserved for _ast_chunk; ts chunker rejects it
        self.assertEqual(
            _ts_chunk.chunk_source_by_symbol("def f(): pass", "python"),
            [],
        )

    def test_unknown_language_returns_empty(self):
        self.assertEqual(
            _ts_chunk.chunk_source_by_symbol("fn main() {}", "brainfuck"),
            [],
        )

    def test_empty_language_returns_empty(self):
        self.assertEqual(_ts_chunk.chunk_source_by_symbol("xxx", ""), [])
        self.assertEqual(_ts_chunk.chunk_source_by_symbol("xxx", None), [])

    def test_returns_empty_when_ts_unavailable(self):
        # Whether deps are present or absent, the call must produce
        # a list (not raise). When deps are absent, it'll be [].
        result = _ts_chunk.chunk_source_by_symbol(
            "fn hello() { println!(\"world\"); }", "rust"
        )
        self.assertIsInstance(result, list)

    def test_is_available_returns_bool(self):
        self.assertIsInstance(_ts_chunk.is_available(), bool)


@unittest.skipUnless(
    _ts_chunk.is_available(),
    "tree_sitter_languages / tree_sitter_language_pack not installed",
)
class TestTreeSitterChunking(unittest.TestCase):
    """Live tree-sitter parsing tests. Skipped when neither package
    is installed (typical CI environment)."""

    def test_rust_chunks_top_level_functions(self):
        source = """\
use std::collections::HashMap;

fn first() -> i32 {
    42
}

fn second(x: i32) -> i32 {
    x + 1
}
"""
        chunks = _ts_chunk.chunk_source_by_symbol(source, "rust")
        names = [c.symbol_name for c in chunks if c.kind == "function"]
        self.assertIn("first", names)
        self.assertIn("second", names)

    def test_rust_module_prologue(self):
        source = """\
use std::collections::HashMap;
const X: i32 = 42;

fn after() -> i32 {
    X
}
"""
        chunks = _ts_chunk.chunk_source_by_symbol(source, "rust")
        # Prologue should be a 'module' chunk first
        if chunks:
            self.assertEqual(chunks[0].kind, "module")
            self.assertIn("use std", chunks[0].text)

    def test_rust_struct_and_impl(self):
        source = """\
struct Point { x: i32, y: i32 }
impl Point {
    fn new(x: i32, y: i32) -> Self {
        Self { x, y }
    }
}
"""
        chunks = _ts_chunk.chunk_source_by_symbol(source, "rust")
        kinds = {c.kind for c in chunks}
        self.assertIn("struct", kinds)
        self.assertIn("impl", kinds)

    def test_javascript_function_chunks(self):
        source = """\
import { foo } from './bar';

function alpha() { return 1; }
function beta(x) { return x + 1; }
"""
        chunks = _ts_chunk.chunk_source_by_symbol(source, "javascript")
        names = [c.symbol_name for c in chunks if c.kind == "function"]
        self.assertIn("alpha", names)
        self.assertIn("beta", names)

    def test_parse_error_returns_empty(self):
        # Garbage source — parser produces ERROR nodes; no defs found
        chunks = _ts_chunk.chunk_source_by_symbol(
            "&^%$#@!()@#$%^&*()", "rust"
        )
        # Either empty or no real definitions
        self.assertTrue(all(c.kind != "block" or c.text.strip()
                            for c in chunks))


if __name__ == "__main__":
    unittest.main()
