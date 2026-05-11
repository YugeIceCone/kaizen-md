#!/usr/bin/env python3
"""Unit tests for docs_gen.py — uses tmp dirs, no network.

Covers:
    - Language detection by manifest marker
    - LOC counting + test-file detection
    - Manifest parsers (Rust, JS, Go, Python)
    - Public API regex extraction
    - Version coercion (workspace-inherited)
    - End-to-end scan_package on a synthetic crate
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "kaizen" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import docs_gen as dg  # noqa: E402


def _scratch() -> Path:
    return Path(tempfile.mkdtemp())


class TestDetect(unittest.TestCase):
    def test_rust(self):
        r = _scratch()
        (r / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
        out = dg.detect_packages(r)
        self.assertEqual(out, [(r, "rust")])

    def test_python(self):
        r = _scratch()
        (r / "pyproject.toml").write_text("[project]\nname = 'y'\n")
        out = dg.detect_packages(r)
        self.assertEqual(out, [(r, "python")])

    def test_skips_ignored_dirs(self):
        r = _scratch()
        (r / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
        nested = r / "target" / "debug"
        nested.mkdir(parents=True)
        (nested / "Cargo.toml").write_text('[package]\nname = "nope"\nversion = "0.0.1"\n')
        out = dg.detect_packages(r)
        # Only the root, not the target/ nested
        self.assertEqual([p[0] for p in out], [r])


class TestVersionCoerce(unittest.TestCase):
    def test_string(self):
        self.assertEqual(dg._coerce_version("0.1.0"), "0.1.0")

    def test_workspace_dict(self):
        self.assertEqual(dg._coerce_version({"workspace": True}), "workspace")

    def test_unknown_dict(self):
        self.assertEqual(dg._coerce_version({"other": True}), "0.0.0")


class TestLocCount(unittest.TestCase):
    def test_rust_loc_and_test_split(self):
        r = _scratch()
        src = r / "src"
        src.mkdir()
        (src / "lib.rs").write_text("pub fn foo() {}\n// comment\n\npub fn bar() {}\n")
        tests = r / "tests"
        tests.mkdir()
        (tests / "integration.rs").write_text("fn t() {}\nfn u() {}\n")
        loc, files = dg.count_loc(r, "rust")
        # 2 non-comment, non-blank lines in src (the two fn lines)
        self.assertEqual(loc["src"], 2)
        self.assertEqual(loc["test"], 2)
        self.assertEqual(files["src"], 1)
        self.assertEqual(files["test"], 1)


class TestParsers(unittest.TestCase):
    def test_rust_parser(self):
        r = _scratch()
        (r / "Cargo.toml").write_text(
            '[package]\nname = "kaizen-test"\nversion = "0.2.3"\n'
            '[dependencies]\nserde = "1"\nanyhow = "1"\n'
            '[dev-dependencies]\nrstest = "0.18"\n'
        )
        out = dg.parse_rust(r)
        self.assertEqual(out["name"], "kaizen-test")
        self.assertEqual(out["version"], "0.2.3")
        self.assertEqual(sorted(out["deps"]), ["anyhow", "serde"])
        self.assertEqual(out["dev_deps"], ["rstest"])

    def test_js_parser(self):
        r = _scratch()
        (r / "package.json").write_text(json.dumps({
            "name": "kaizen-js",
            "version": "1.2.3",
            "dependencies": {"react": "^18", "lodash": "^4"},
            "devDependencies": {"jest": "^29"},
        }))
        out = dg.parse_js(r)
        self.assertEqual(out["name"], "kaizen-js")
        self.assertEqual(out["version"], "1.2.3")
        self.assertIn("react", out["deps"])
        self.assertIn("jest", out["dev_deps"])

    def test_go_parser(self):
        r = _scratch()
        (r / "go.mod").write_text(
            "module github.com/yic/kaizen-go\n\n"
            "go 1.22\n\n"
            "require (\n"
            "\tgithub.com/spf13/cobra v1.7.0\n"
            "\tgolang.org/x/sync v0.5.0\n"
            ")\n"
        )
        out = dg.parse_go(r)
        self.assertEqual(out["name"], "kaizen-go")
        self.assertIn("github.com/spf13/cobra", out["deps"])


class TestPublicApi(unittest.TestCase):
    def test_rust_api_extraction(self):
        r = _scratch()
        src = r / "src"
        src.mkdir()
        (src / "lib.rs").write_text(
            "pub fn build_registry() {}\n"
            "pub async fn dispatch() {}\n"
            "pub struct Context;\n"
            "pub trait Node {}\n"
            "pub enum Cap { A, B }\n"
            "fn private() {}\n"  # not pub — should NOT be counted
        )
        api = dg.public_api(r, "rust")
        self.assertEqual(api["fn"], 2)
        self.assertEqual(api["struct"], 1)
        self.assertEqual(api["trait"], 1)
        self.assertEqual(api["enum"], 1)
        self.assertIn("build_registry", api["names"])
        self.assertNotIn("private", api["names"])


class TestScanPackage(unittest.TestCase):
    def test_end_to_end_rust(self):
        r = _scratch()
        (r / "Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\n')
        src = r / "src"
        src.mkdir()
        (src / "lib.rs").write_text("pub fn run() {}\npub struct App;\n")
        record = dg.scan_package(r, "rust", r)
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["kind"], "kaizen.docs")
        self.assertEqual(record["name"], "demo")
        self.assertEqual(record["language"], "rust")
        self.assertEqual(record["version"], "0.1.0")
        self.assertEqual(record["loc"]["total"], 2)
        self.assertEqual(record["public_api"]["fn"], 1)
        self.assertEqual(record["public_api"]["struct"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
