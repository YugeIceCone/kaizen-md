#!/usr/bin/env python3
"""Tests for docs_flow.py — pocketflow-shaped docs-gen pipeline.

Run:
    python3 -m unittest tests.test_docs_flow -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import docs_flow as df  # noqa: E402


def _seed_workspace(root: Path) -> None:
    """Two packages — one rust, one python — both with minimal source."""
    # Rust package
    rust = root / "crates" / "alpha"
    rust.mkdir(parents=True)
    (rust / "Cargo.toml").write_text(
        '[package]\nname = "alpha"\nversion = "0.1.0"\nedition = "2024"\n'
    )
    (rust / "src").mkdir()
    (rust / "src" / "lib.rs").write_text(
        "//! alpha crate.\n\npub fn entry() {}\npub struct Thing;\n"
    )
    # Python package — sit directly under root so the path-derived
    # `name` is just `beta`, matching shodan's `crates/<x>` shape after
    # the prefix-strip in analyze_package.
    py = root / "beta"
    py.mkdir()
    (py / "pyproject.toml").write_text(
        '[project]\nname = "beta"\nversion = "0.2.0"\n'
        'description = "Beta package."\n'
    )
    (py / "beta").mkdir()
    (py / "beta" / "__init__.py").write_text(
        '"""beta — example."""\n\ndef public(): pass\nclass W: pass\n'
    )


class TestDetectPackages(unittest.TestCase):
    def test_finds_two_packages_in_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_workspace(root)
            node = df.DetectPackagesNode()
            store: dict = {"root": root}
            action = asyncio.run(node.run_async(store))
            self.assertEqual(action, "default")
            self.assertEqual(store["package_count"], 2)
            langs = sorted(lang for _, lang in store["packages"])
            self.assertEqual(langs, ["python", "rust"])

    def test_emits_empty_action_when_no_packages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = df.DetectPackagesNode()
            store: dict = {"root": root}
            action = asyncio.run(node.run_async(store))
            self.assertEqual(action, "empty")
            self.assertEqual(store["package_count"], 0)


class TestEndToEndDocsFlow(unittest.TestCase):
    def test_writes_md_and_json_per_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "out"
            _seed_workspace(root)
            report = df.docs_scan(root, out_dir, format="both")
            self.assertEqual(report["package_count"], 2)
            self.assertEqual(report["files_written"], 4)  # 2 pkgs × 2 formats
            files = sorted(p.name for p in out_dir.iterdir())
            self.assertIn("ALPHA.md", files)
            self.assertIn("ALPHA.json", files)
            self.assertIn("BETA.md", files)
            self.assertIn("BETA.json", files)
            # Verify content has the expected shape
            md = (out_dir / "ALPHA.md").read_text()
            self.assertIn("## 1. What `alpha` is", md)
            self.assertIn("## 2. Files", md)
            self.assertIn("## 3. Public API at a glance", md)
            j = json.loads((out_dir / "BETA.json").read_text())
            self.assertEqual(j["package_name"], "beta")
            self.assertEqual(j["language"], "python")

    def test_md_only_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "out"
            _seed_workspace(root)
            report = df.docs_scan(root, out_dir, format="md")
            self.assertEqual(report["files_written"], 2)
            files = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(files, ["ALPHA.md", "BETA.md"])

    def test_only_restricts_to_named_packages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "out"
            _seed_workspace(root)
            report = df.docs_scan(root, out_dir, only={"alpha"})
            self.assertEqual(report["package_count"], 1)
            files = sorted(p.name for p in out_dir.iterdir())
            self.assertEqual(files, ["ALPHA.json", "ALPHA.md"])


class TestEmptyWorkspace(unittest.TestCase):
    def test_empty_dir_returns_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "out"
            report = df.docs_scan(root, out_dir)
            self.assertEqual(report["package_count"], 0)
            self.assertEqual(report["files_written"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
