#!/usr/bin/env python3
"""Tests for docs_gen.py — v2 port of shodan's `cargo xtask docs`.

Coverage:
  - Rust signature extraction (fn / async fn / struct / trait / enum / macro)
  - Rust module-doc extraction (`//!` block, with `#![…]` banner skip)
  - Rust manifest parsing (workspace deps, direct deps, inline tables, features, bins)
  - Python signature extraction (def / async def / class; skips private)
  - Python module-doc extraction (triple-double / triple-single)
  - End-to-end: analyze_package() on synthetic Rust + Python projects,
    then render_md() with all 9 sections present.

Run:
    python3 -m unittest tests.test_docs_gen -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import docs_gen as dg  # noqa: E402

class TestRustItemExtraction(unittest.TestCase):
    def test_extracts_pub_fn_with_signature(self) -> None:
        src = "pub fn foo(a: i32) -> Result<()> {\n    Ok(())\n}\n"
        items = dg._extract_rust_items(src)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "fn")
        self.assertEqual(items[0].name, "foo")
        self.assertIn("pub fn foo", items[0].signature)
        self.assertIn("Result", items[0].signature)

    def test_async_fn_classified_separately(self) -> None:
        items = dg._extract_rust_items("pub async fn bar() -> u64 { 0 }\n")
        self.assertEqual(items[0].kind, "async_fn")
        self.assertEqual(items[0].name, "bar")

    def test_struct_trait_enum_const_type(self) -> None:
        src = (
            "pub struct S<T> { x: T }\n"
            "pub trait T { fn f(&self); }\n"
            "pub enum E { A, B }\n"
            "pub const C: u32 = 7;\n"
            "pub type Alias = Result<()>;\n"
        )
        kinds = sorted(it.kind for it in dg._extract_rust_items(src))
        self.assertEqual(kinds, ["const", "enum", "struct", "trait", "type_alias"])

    def test_macro_extraction(self) -> None:
        items = dg._extract_rust_items("macro_rules! hello {\n    () => { 1 };\n}\n")
        self.assertEqual(items[0].kind, "macro")
        self.assertEqual(items[0].name, "hello")
        self.assertEqual(items[0].signature, "macro_rules! hello")

    def test_dedupes_kind_name(self) -> None:
        items = dg._extract_rust_items("pub fn foo() {}\npub fn foo() {}\n")
        self.assertEqual(len(items), 1)

    def test_pub_crate_pub_super_captured(self) -> None:
        src = "pub(crate) fn private() {}\npub fn public() {}\n"
        names = sorted(it.name for it in dg._extract_rust_items(src))
        self.assertEqual(names, ["private", "public"])

    def test_pub_use_not_item(self) -> None:
        self.assertEqual(dg._extract_rust_items("pub use crate::foo::Bar;\n"), [])

class TestRustModuleDoc(unittest.TestCase):
    def test_extracts_first_paragraph(self) -> None:
        src = "//! Crate doc.\n//! Second line.\n//!\n//! Second paragraph.\n\nfn x() {}\n"
        self.assertEqual(dg._extract_rust_module_doc(src), "Crate doc. Second line.")

    def test_skips_inner_attr_banner(self) -> None:
        src = "#![allow(dead_code)]\n\n//! Hello.\n"
        self.assertEqual(dg._extract_rust_module_doc(src), "Hello.")

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(dg._extract_rust_module_doc("fn x() {}\n"))

class TestRustManifest(unittest.TestCase):
    def test_parses_workspace_and_direct_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "p"
            pkg.mkdir()
            (pkg / "Cargo.toml").write_text(
                "[package]\n"
                'name = "test-pkg"\n'
                'version = "0.1.0"\n'
                'edition = "2024"\n'
                'description = "A test crate."\n'
                "\n[dependencies]\n"
                "anyhow.workspace = true\n"
                'serde = { workspace = true, features = ["derive"] }\n'
                'rand = "0.8"\n'
                "\n[dev-dependencies]\n"
                "criterion.workspace = true\n"
                "\n[features]\n"
                'default = ["std"]\n'
                'std = []\n'
                "\n[[bin]]\n"
                'name = "test-bin"\n'
                'path = "src/main.rs"\n'
            )
            meta, bins, features, deps, dev_deps, lints = dg.parse_rust_manifest(pkg)
            self.assertEqual(meta.name, "test-pkg")
            self.assertEqual(meta.version, "0.1.0")
            self.assertEqual(meta.edition, "2024")
            self.assertEqual(meta.description, "A test crate.")
            self.assertEqual({d.name for d in deps}, {"anyhow", "serde", "rand"})
            anyhow = next(d for d in deps if d.name == "anyhow")
            self.assertEqual(anyhow.source, "workspace")
            serde = next(d for d in deps if d.name == "serde")
            self.assertEqual(serde.source, "workspace")
            self.assertEqual(serde.features, "derive")
            rand = next(d for d in deps if d.name == "rand")
            self.assertIn("version", rand.source)
            self.assertEqual([d.name for d in dev_deps], ["criterion"])
            self.assertEqual({f.name for f in features}, {"default", "std"})
            self.assertEqual(len(bins), 1)
            self.assertEqual(bins[0].name, "test-bin")
            self.assertEqual(bins[0].path, "src/main.rs")

class TestPythonItemExtraction(unittest.TestCase):
    def test_extracts_top_level_def_and_class(self) -> None:
        src = (
            'def foo(x: int) -> int:\n    return x + 1\n\n'
            'class Bar:\n    def method(self): pass\n\n'
            'async def baz():\n    pass\n'
        )
        items = dg._extract_python_items(src)
        names_by_kind = {kind: sorted(i.name for i in items if i.kind == kind)
                         for kind in {it.kind for it in items}}
        self.assertIn("foo", names_by_kind.get("fn", []))
        self.assertIn("Bar", names_by_kind.get("class", []))
        self.assertIn("baz", names_by_kind.get("async_fn", []))
        self.assertNotIn("method", [i.name for i in items])

    def test_skips_private_single_underscore(self) -> None:
        src = (
            'def _private():\n    pass\n'
            'def __dunder__():\n    pass\n'
            'def visible():\n    pass\n'
        )
        names = [it.name for it in dg._extract_python_items(src)]
        self.assertNotIn("_private", names)
        self.assertIn("__dunder__", names)
        self.assertIn("visible", names)

class TestPythonModuleDoc(unittest.TestCase):
    def test_triple_double(self) -> None:
        src = '"""Hello.\n\nMore text.\n"""\nimport os\n'
        self.assertEqual(dg._extract_python_module_doc(src), "Hello.")

    def test_single_line(self) -> None:
        self.assertEqual(dg._extract_python_module_doc('"""One-liner."""\nimport os\n'), "One-liner.")

    def test_after_future_imports(self) -> None:
        src = 'from __future__ import annotations\n\n"""Real docstring."""\nx = 1\n'
        self.assertEqual(dg._extract_python_module_doc(src), "Real docstring.")

    def test_none_when_absent(self) -> None:
        self.assertIsNone(dg._extract_python_module_doc('import os\n\nx = 1\n'))

class TestAnalyzeRustPackage(unittest.TestCase):
    def _build(self, root: Path) -> Path:
        pkg = root / "test-crate"
        pkg.mkdir()
        (pkg / "Cargo.toml").write_text(
            '[package]\n'
            'name = "shodan-test"\n'
            'version = "0.1.0"\n'
            'edition = "2024"\n'
            '[dependencies]\n'
            'anyhow.workspace = true\n'
        )
        src = pkg / "src"
        src.mkdir()
        (src / "lib.rs").write_text(
            "//! shodan-test — exercises the docs generator.\n"
            "//!\n"
            "//! Second paragraph.\n\n"
            "pub fn entry() {}\n"
            "pub struct Thing<T> { x: T }\n\n"
            "pub use crate::nested::Item;\n\n"
            "mod nested { pub struct Item; }\n\n"
            "#[cfg(test)]\nmod tests {\n"
            "    #[test]\n"
            "    fn smoke() { assert_eq!(1 + 1, 2); }\n"
            "}\n"
        )
        return pkg

    def test_analyzes_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = self._build(root)
            profile = dg.analyze_package(pkg, "rust", root)
            self.assertEqual(profile.package_name, "shodan-test")
            self.assertEqual(profile.edition, "2024")
            self.assertEqual(len(profile.files), 1)
            self.assertGreater(profile.total_loc, 0)
            self.assertEqual(profile.total_tests, 1)
            self.assertIsNotNone(profile.crate_doc)
            self.assertIn("shodan-test", profile.crate_doc)
            self.assertEqual([d.name for d in profile.dependencies], ["anyhow"])
            self.assertIn("crate::nested::Item", " ".join(profile.re_exports))

    def test_render_md_has_all_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = self._build(root)
            profile = dg.analyze_package(pkg, "rust", root)
            md = dg.render_md(profile)
            self.assertIn(f"# `crates/{profile.relative_path}/`", md)
            for n in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                self.assertRegex(md, rf"## {n}\.")
            self.assertIn("### Functions", md)
            self.assertIn("| Name | File | Signature |", md)
            self.assertIn(f"{profile.total_loc} LOC", md)
            self.assertIn(f"~{profile.total_tests} test attribute", md)
            self.assertIn("crate::nested::Item", md)

class TestAnalyzePythonPackage(unittest.TestCase):
    def test_analyzes_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "my-pkg"
            pkg.mkdir()
            (pkg / "pyproject.toml").write_text(
                '[project]\n'
                'name = "my-pkg"\n'
                'version = "0.1.0"\n'
                'description = "A test python package."\n'
                'dependencies = ["requests>=2.0", "click==8.1"]\n'
            )
            src = pkg / "my_pkg"
            src.mkdir()
            (src / "__init__.py").write_text(
                '"""my-pkg — top-level docstring."""\n\n'
                'def public(): pass\n'
                'class Widget: pass\n'
                'def _private(): pass\n'
            )
            (src / "tests.py").write_text(
                'def test_one(): pass\n'
                'def test_two(): pass\n'
            )
            profile = dg.analyze_package(pkg, "python", root)
            self.assertEqual(profile.package_name, "my-pkg")
            self.assertEqual(profile.version, "0.1.0")
            self.assertEqual(profile.package_description, "A test python package.")
            self.assertEqual({d.name for d in profile.dependencies}, {"requests", "click"})
            self.assertEqual(len(profile.files), 2)
            self.assertEqual(profile.total_tests, 2)
            self.assertIsNotNone(profile.crate_doc)
            self.assertIn("my-pkg", profile.crate_doc)
            md = dg.render_md(profile)
            self.assertIn("## 1. What `my-pkg` is", md)
            self.assertIn("A test python package.", md)
            self.assertIn("### Functions", md)
            self.assertIn("### Classes", md)

class TestJsonRoundtrip(unittest.TestCase):
    def test_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "p"
            pkg.mkdir()
            (pkg / "Cargo.toml").write_text(
                '[package]\nname = "x"\nversion = "0.1.0"\n'
            )
            (pkg / "src").mkdir()
            (pkg / "src" / "lib.rs").write_text("pub fn f() {}\n")
            profile = dg.analyze_package(pkg, "rust", root)
            blob = profile.to_json()
            text = json.dumps(blob)
            again = json.loads(text)
            self.assertEqual(again["schema_version"], dg.SCHEMA_VERSION)
            self.assertEqual(again["kind"], dg.KIND)
            self.assertEqual(again["package_name"], "x")

if __name__ == "__main__":
    unittest.main(verbosity=2)
