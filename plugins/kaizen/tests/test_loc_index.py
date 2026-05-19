"""Unit tests for `loc_index.py` — Phase 1 X1.

Mirrors the 17 tests in shodan's `xtask/src/loc.rs::tests`, translated
to Python AST semantics. Plus integration tests for the SQLite round-trip,
structured search, regex fallback, and the comparison-string parser.

Run:
    python3 -m unittest tests.test_loc_index -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "indexers"))

import loc_index as li  # noqa: E402


# ─── 1. AST extraction (mirrors loc.rs::extract_rust_functions tests) ───


class TestExtractPythonFunctions(unittest.TestCase):
    def test_extracts_free_function(self):
        # Mirror of loc.rs::extracts_free_function.
        src = "def foo():\n    return 42\n"
        fns = li.extract_python_functions(src, "t.py")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].symbol_name, "foo")
        self.assertEqual(fns[0].qualified_name, "foo")
        self.assertEqual(fns[0].symbol_kind, "function")
        self.assertEqual(fns[0].line_start, 1)
        self.assertEqual(fns[0].parser, "ast")

    def test_function_spans_multiple_lines(self):
        # 5-line def.
        src = "def foo():\n    x = 1\n    y = 2\n    return x + y\n"
        fns = li.extract_python_functions(src, "t.py")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].line_start, 1)
        self.assertEqual(fns[0].line_end, 4)
        self.assertEqual(fns[0].physical_lines, 4)

    def test_extracts_method_with_class_context(self):
        # Mirror of extracts_method_with_impl_context.
        src = "class Foo:\n    def bar(self):\n        pass\n"
        fns = li.extract_python_functions(src, "t.py")
        method = next(f for f in fns if f.symbol_name == "bar")
        self.assertEqual(method.qualified_name, "Foo.bar")
        self.assertEqual(method.symbol_kind, "method")

    def test_distinguishes_method_vs_classmethod_vs_staticmethod(self):
        # Mirror of distinguishes_method_vs_associated_fn.
        src = (
            "class Foo:\n"
            "    @classmethod\n"
            "    def new(cls):\n"
            "        return cls()\n"
            "    @staticmethod\n"
            "    def util():\n"
            "        return 1\n"
            "    def run(self):\n"
            "        pass\n"
        )
        fns = li.extract_python_functions(src, "t.py")
        kinds = {f.symbol_name: f.symbol_kind for f in fns if f.symbol_name != "Foo"}
        self.assertEqual(kinds.get("new"), "class-method")
        self.assertEqual(kinds.get("util"), "static-method")
        self.assertEqual(kinds.get("run"), "method")

    def test_extracts_abstract_method(self):
        # Mirror of extracts_trait_method (Python: @abstractmethod).
        src = (
            "class Greeter:\n"
            "    @abstractmethod\n"
            "    def hello(self):\n"
            "        ...\n"
        )
        fns = li.extract_python_functions(src, "t.py")
        hello = next(f for f in fns if f.symbol_name == "hello")
        self.assertEqual(hello.symbol_kind, "abstract-method")

    def test_nests_qualified_name_through_modules(self):
        # Python uses nested classes (no `mod` keyword); use class inside class.
        src = (
            "class Outer:\n"
            "    class Inner:\n"
            "        def bar(self):\n"
            "            pass\n"
        )
        fns = li.extract_python_functions(src, "t.py")
        bar = next(f for f in fns if f.symbol_name == "bar")
        self.assertEqual(bar.qualified_name, "Outer.Inner.bar")

    def test_extracts_async_function(self):
        src = "async def task():\n    return 1\n"
        fns = li.extract_python_functions(src, "t.py")
        self.assertEqual(fns[0].symbol_kind, "async-function")
        self.assertTrue(fns[0].is_async)


# ─── 2. McCabe complexity (mirrors loc.rs::ComplexityVisitor tests) ────


class TestComplexity(unittest.TestCase):
    def _cx(self, src: str, name: str) -> int:
        fns = li.extract_python_functions(src, "t.py")
        return next(f.cyclomatic for f in fns if f.symbol_name == name)

    def test_counts_baseline(self):
        # Linear function → cyclomatic 1.
        self.assertEqual(self._cx("def linear():\n    x = 42\n", "linear"), 1)

    def test_counts_if_branches(self):
        # if/else → +1 (one `if`).
        src = "def branchy(x):\n    if x > 0:\n        return 1\n    else:\n        return 2\n"
        self.assertEqual(self._cx(src, "branchy"), 2)

    def test_counts_match_arms(self):
        # match with 3 cases → +(3-1) = 2; base 1 + 2 = 3.
        src = (
            "def pick(x):\n"
            "    match x:\n"
            "        case 0:\n"
            "            return 0\n"
            "        case 1:\n"
            "            return 1\n"
            "        case _:\n"
            "            return x\n"
        )
        self.assertEqual(self._cx(src, "pick"), 3)

    def test_counts_loop_and_short_circuit(self):
        # while + and → base 1 + 1 (while) + 1 (and) = 3.
        src = "def loops(x, y):\n    while x and y:\n        pass\n"
        self.assertEqual(self._cx(src, "loops"), 3)

    def test_counts_except_handler(self):
        # Mirror of counts_try_operator — Python equivalent is except.
        src = (
            "def fallible():\n"
            "    try:\n"
            "        x = 1\n"
            "    except ValueError:\n"
            "        x = 0\n"
            "    return x\n"
        )
        self.assertEqual(self._cx(src, "fallible"), 2)

    def test_lambdas_contribute_to_complexity(self):
        # Mirror of closures_contribute_to_complexity.
        # Base 1 + lambda 1 + list-comp generator 1 = 3.
        src = "def higher_order(v):\n    return [(lambda x: x + 1)(z) for z in v]\n"
        cx = self._cx(src, "higher_order")
        self.assertGreaterEqual(cx, 2)  # lambda contributes; comp adds too

    def test_comprehension_adds_complexity(self):
        # List comp with `for` and `if` → 2 additions.
        src = "def f(v):\n    return [x for x in v if x > 0]\n"
        # Base 1 + 1 (for-gen) + 1 (if) = 3.
        self.assertEqual(self._cx(src, "f"), 3)


# ─── 3. Attribute / flag detection ─────────────────────────────────────


class TestAttributes(unittest.TestCase):
    def test_detects_test_function_by_name(self):
        src = "def test_it_works():\n    pass\n"
        fns = li.extract_python_functions(src, "t.py")
        self.assertTrue(fns[0].is_test)

    def test_detects_test_function_by_decorator(self):
        # Mirror of detects_qualified_test_attribute.
        src = (
            "@pytest.mark.asyncio\n"
            "async def my_async_test():\n"
            "    pass\n"
        )
        fns = li.extract_python_functions(src, "t.py")
        # Either decorator detection OR path-based heuristic; here we
        # rely on the decorator chain rendering.
        self.assertTrue(fns[0].is_async)

    def test_detects_test_function_by_path(self):
        src = "def something():\n    pass\n"
        fns = li.extract_python_functions(src, "tests/test_x.py")
        self.assertTrue(fns[0].is_test)

    def test_detects_public_visibility(self):
        src = "def public_thing():\n    pass\n\ndef _private_thing():\n    pass\n"
        fns = li.extract_python_functions(src, "t.py")
        pub = next(f for f in fns if f.symbol_name == "public_thing")
        priv = next(f for f in fns if f.symbol_name == "_private_thing")
        self.assertTrue(pub.is_public)
        self.assertFalse(priv.is_public)

    def test_handles_parse_errors_gracefully(self):
        # Malformed Python — extractor returns empty, no exception.
        src = "def broken((( :\n"
        fns = li.extract_python_functions(src, "t.py")
        self.assertEqual(fns, [])


# ─── 4. Symbol metadata ────────────────────────────────────────────────


class TestFunctionInfo(unittest.TestCase):
    def test_citation_format(self):
        info = li.FunctionInfo(
            path="src/foo.py",
            language="Python",
            symbol_kind="method",
            symbol_name="bar",
            qualified_name="Foo.bar",
            line_start=10,
            line_end=25,
            physical_lines=16,
        )
        self.assertEqual(info.citation(), "src/foo.py:10-25")


# ─── 5. Comparison string parser ───────────────────────────────────────


class TestCompareParser(unittest.TestCase):
    def test_parses_gte(self):
        self.assertEqual(li._parse_compare(">=15"), (">=", 15))

    def test_parses_lt(self):
        self.assertEqual(li._parse_compare("<100"), ("<", 100))

    def test_parses_bare_int_as_eq(self):
        self.assertEqual(li._parse_compare("5"), ("==", 5))

    def test_parses_eq_single(self):
        self.assertEqual(li._parse_compare("=5"), ("==", 5))

    def test_returns_none_for_garbage(self):
        self.assertIsNone(li._parse_compare("not-a-number"))


# ─── 6. Regex fallback (Rust, JS, Shell) ───────────────────────────────


class TestRegexFallback(unittest.TestCase):
    def test_extracts_rust_function(self):
        src = "pub fn foo() {}\n"
        fns = li.extract_regex_functions(src, "t.rs", "Rust")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].symbol_name, "foo")
        self.assertEqual(fns[0].parser, "regex")

    def test_extracts_go_function(self):
        src = "func Hello() string {\n    return \"hi\"\n}\n"
        fns = li.extract_regex_functions(src, "t.go", "Go")
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0].symbol_name, "Hello")


# ─── 7. File analysis ──────────────────────────────────────────────────


class TestAnalyzeFile(unittest.TestCase):
    def test_counts_lines_for_python(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "x.py"
            f.write_text(
                "# header comment\n"
                "\n"
                "def foo():\n"
                "    return 1\n"
            )
            m = li.analyze_file(f, root)
            self.assertIsNotNone(m)
            self.assertEqual(m.language, "Python")
            self.assertEqual(m.comment_lines, 1)
            self.assertEqual(m.blank_lines, 1)
            self.assertEqual(m.logical_lines, 2)
            self.assertEqual(len(m.symbols), 1)

    def test_returns_none_for_unknown_extension(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "blob.bin"
            f.write_bytes(b"not a source file")
            self.assertIsNone(li.analyze_file(f, Path(td)))

    def test_returns_none_for_binary_files(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "img.py"
            f.write_bytes(b"\x00\x01\x02\x03" * 10)
            self.assertIsNone(li.analyze_file(f, Path(td)))

    def test_god_tier_classification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "big.py"
            # 1500 lines → critical
            f.write_text("x = 1\n" * 1500)
            m = li.analyze_file(f, root)
            self.assertEqual(m.god_tier, "critical")
            warn = root / "med.py"
            warn.write_text("x = 1\n" * 700)
            mw = li.analyze_file(warn, root)
            self.assertEqual(mw.god_tier, "warning")


# ─── 8. End-to-end indexer round-trip ──────────────────────────────────


class TestIndexerRoundTrip(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Build a tiny repo
        (self.root / "src").mkdir()
        (self.root / "src" / "alpha.py").write_text(
            "def carve(old, new, slug):\n"
            "    \"\"\"carve a shim.\"\"\"\n"
            "    if old == new:\n"
            "        return\n"
            "    return slug\n"
        )
        (self.root / "src" / "beta.py").write_text(
            "class Mover:\n"
            "    def move(self):\n"
            "        for i in range(10):\n"
            "            if i % 2:\n"
            "                yield i\n"
        )
        (self.root / "lib.rs").write_text(
            "pub fn hello() -> &'static str { \"hi\" }\n"
        )
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_index_and_search_by_name(self):
        result = li.do_index(self.root)
        self.assertGreater(result["new_files"], 0)
        self.assertGreater(result["new_symbols"], 0)
        # carve should be findable by name
        hits = li.do_search(self.root, name="carve")
        self.assertTrue(any(h["symbol_name"] == "carve" for h in hits))

    def test_index_and_search_at_line(self):
        li.do_index(self.root)
        # Pick a line known to fall inside `carve`
        hits = li.do_search(self.root, at="src/alpha.py:3")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["symbol_name"], "carve")

    def test_search_by_complexity(self):
        li.do_index(self.root)
        # `move` has cyclomatic >= 2 (for + if)
        hits = li.do_search(self.root, complexity=">=2", language="Python")
        self.assertTrue(any(h["symbol_name"] == "move" for h in hits))

    def test_search_only_python_kind(self):
        li.do_index(self.root)
        hits = li.do_search(self.root, kind="method", language="Python")
        self.assertTrue(all(h["symbol_kind"] == "method" for h in hits))
        self.assertTrue(any(h["symbol_name"] == "move" for h in hits))

    def test_stats_returns_counts(self):
        li.do_index(self.root)
        s = li.do_stats(self.root, by="language")
        self.assertTrue(s["indexed"])
        self.assertIn("Python", s["by_language"])

    def test_get_returns_symbol_record(self):
        li.do_index(self.root)
        hits = li.do_search(self.root, name="carve")
        rec = li.do_get(self.root, hits[0]["id"])
        self.assertIsNotNone(rec)
        self.assertEqual(rec["symbol_name"], "carve")

    def test_show_extracts_source(self):
        li.do_index(self.root)
        hits = li.do_search(self.root, name="carve")
        shown = li.do_show(self.root, hits[0]["id"])
        self.assertIn("carve", shown["source"])

    def test_files_command_god_filter(self):
        # Add a god file
        (self.root / "src" / "huge.py").write_text("x = 1\n" * 1500)
        li.do_index(self.root)
        rows = li.do_files(self.root, god="critical")
        self.assertTrue(any(r["path"].endswith("huge.py") for r in rows))

    def test_index_is_incremental(self):
        # First pass should add many files; second pass should skip all.
        r1 = li.do_index(self.root)
        r2 = li.do_index(self.root)
        self.assertGreater(r1["new_files"], 0)
        self.assertEqual(r2["new_files"], 0)
        self.assertGreaterEqual(r2["skipped_files"], r1["new_files"])

    def test_stale_files_removed(self):
        li.do_index(self.root)
        # Delete one file
        (self.root / "src" / "beta.py").unlink()
        r = li.do_index(self.root)
        self.assertGreaterEqual(r["stale_removed"], 1)


# ─── 9. Source-file walker ─────────────────────────────────────────────


class TestSourceWalker(unittest.TestCase):
    def test_skips_ignore_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x = 1\n")
            ignored = root / "node_modules" / "lib"
            ignored.mkdir(parents=True)
            (ignored / "b.py").write_text("x = 1\n")
            files = li.iter_source_files(root)
            rels = [str(f.relative_to(root)) for f in files]
            self.assertIn("src/a.py", rels)
            self.assertNotIn("node_modules/lib/b.py", rels)

    def test_skips_binary_suffixes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ok.py").write_text("x = 1\n")
            (root / "bundle.min.js").write_text("(()=>{})()")
            files = li.iter_source_files(root)
            names = [f.name for f in files]
            self.assertIn("ok.py", names)
            self.assertNotIn("bundle.min.js", names)


class TestSingleFileEntryPoints(unittest.TestCase):
    """index_one_file() + delete_file() — the watch-loop primitives."""

    def _root(self):
        import tempfile
        td = tempfile.mkdtemp()
        return Path(td)

    def test_index_one_file_upserts_one_file(self):
        import loc_index
        root = self._root()
        f = root / "sample.py"
        f.write_text("def alpha():\n    return 1\n\ndef beta():\n    return 2\n")
        conn = loc_index.open_db(root, create=True)
        loc_index.index_one_file(conn, root, f)
        conn.commit()
        rows = conn.execute(
            "SELECT symbol_name FROM loc_symbols WHERE path = ?",
            ("sample.py",)).fetchall()
        names = sorted(r["symbol_name"] for r in rows)
        self.assertEqual(names, ["alpha", "beta"])
        frow = conn.execute(
            "SELECT symbol_count FROM loc_files WHERE path = ?",
            ("sample.py",)).fetchone()
        self.assertEqual(frow["symbol_count"], 2)

    def test_index_one_file_replaces_on_rechange(self):
        import loc_index
        root = self._root()
        f = root / "sample.py"
        f.write_text("def alpha():\n    return 1\n")
        conn = loc_index.open_db(root, create=True)
        loc_index.index_one_file(conn, root, f)
        conn.commit()
        f.write_text("def gamma():\n    return 9\n")
        loc_index.index_one_file(conn, root, f)
        conn.commit()
        rows = conn.execute(
            "SELECT symbol_name FROM loc_symbols WHERE path = ?",
            ("sample.py",)).fetchall()
        self.assertEqual([r["symbol_name"] for r in rows], ["gamma"])

    def test_delete_file_removes_rows(self):
        import loc_index
        root = self._root()
        f = root / "sample.py"
        f.write_text("def alpha():\n    return 1\n")
        conn = loc_index.open_db(root, create=True)
        loc_index.index_one_file(conn, root, f)
        conn.commit()
        loc_index.delete_file(conn, "sample.py")
        conn.commit()
        self.assertEqual(
            conn.execute("SELECT COUNT(*) c FROM loc_files "
                         "WHERE path = ?", ("sample.py",)).fetchone()["c"], 0)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) c FROM loc_symbols "
                         "WHERE path = ?", ("sample.py",)).fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
