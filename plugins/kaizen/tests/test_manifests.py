"""Tests for X3 + M3 — multi-language manifest hygiene + MCP.

Runs the per-language adapters against tmpdir fixtures. Each adapter
parses its canonical manifest format + heuristically detects unused
deps by grepping a tiny source tree.

Run:
    python3 -m unittest tests.test_manifests -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))

import _manifests as m  # noqa: E402


def _write(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"))


# ─── Cargo adapter ────────────────────────────────────────────────────


class TestCargoAdapter(unittest.TestCase):
    def setUp(self):
        self.a = m.CargoAdapter()

    def test_detects_cargo_toml(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "Cargo.toml", '[package]\nname = "x"\n')
            _write(tmp / "target" / "Cargo.toml", "[package]")  # skip
            paths = self.a.detect(tmp)
            self.assertEqual([str(p) for p in paths], [str(tmp / "Cargo.toml")])

    def test_parses_deps_inline_and_table(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "Cargo.toml", '''
                [package]
                name = "x"

                [dependencies]
                serde = "1.0"
                tokio = { version = "1", features = ["full"] }

                [dev-dependencies]
                proptest = "1.0"
            ''')
            mf = self.a.parse(tmp / "Cargo.toml")
            self.assertIsNotNone(mf)
            names = {d.name for d in mf.deps}
            self.assertIn("serde", names)
            self.assertIn("tokio", names)
            self.assertIn("proptest", names)
            dev = [d for d in mf.deps if d.kind == "dev"]
            self.assertEqual([d.name for d in dev], ["proptest"])

    def test_parses_workspace_dependencies(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "Cargo.toml", '''
                [workspace]

                [workspace.dependencies]
                anyhow = "1.0"
                serde = { version = "1", features = ["derive"] }
            ''')
            mf = self.a.parse(tmp / "Cargo.toml")
            ws = [d for d in mf.deps if d.kind == "workspace"]
            self.assertEqual({d.name for d in ws}, {"anyhow", "serde"})

    def test_used_in_source_hyphen_to_underscore(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            src = tmp / "src" / "lib.rs"
            _write(src, "use serde_json::Value;\n")
            files = list((tmp / "src").rglob("*.rs"))
            self.assertTrue(self.a.used_in_source("serde-json", files))
            self.assertFalse(self.a.used_in_source("totally-unused", files))


# ─── package.json adapter ────────────────────────────────────────────


class TestPackageJsonAdapter(unittest.TestCase):
    def setUp(self):
        self.a = m.PackageJsonAdapter()

    def test_parses_deps_and_devdeps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "package.json", json.dumps({
                "dependencies": {"react": "^18.0.0"},
                "devDependencies": {"jest": "^29.0.0"},
            }))
            mf = self.a.parse(tmp / "package.json")
            names = {d.name: d.kind for d in mf.deps}
            self.assertEqual(names, {"react": "", "jest": "dev"})

    def test_skips_node_modules(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "package.json", '{}')
            _write(tmp / "node_modules" / "x" / "package.json", '{}')
            paths = self.a.detect(tmp)
            self.assertEqual([str(p) for p in paths], [str(tmp / "package.json")])

    def test_used_in_source_quoted_import(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "src" / "a.ts",
                   'import { useState } from "react";\n')
            files = list((tmp / "src").rglob("*.ts"))
            self.assertTrue(self.a.used_in_source("react", files))
            self.assertFalse(self.a.used_in_source("lodash", files))

    def test_substring_dep_not_matched_falsely(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "src" / "a.ts",
                   'import "react-dom";\n')  # NOT "react"
            files = list((tmp / "src").rglob("*.ts"))
            self.assertFalse(self.a.used_in_source("react", files))


# ─── pyproject adapter ───────────────────────────────────────────────


class TestPyprojectAdapter(unittest.TestCase):
    def setUp(self):
        self.a = m.PyprojectAdapter()

    def test_parses_pep621_deps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "pyproject.toml", '''
                [project]
                name = "x"
                dependencies = [
                    "requests>=2.0",
                    "numpy",
                ]
                [project.optional-dependencies]
                dev = ["pytest>=7"]
            ''')
            mf = self.a.parse(tmp / "pyproject.toml")
            names = {d.name for d in mf.deps}
            self.assertIn("requests", names)
            self.assertIn("numpy", names)
            opt = [d for d in mf.deps if d.kind.startswith("optional:")]
            self.assertEqual([d.name for d in opt], ["pytest"])

    def test_parses_poetry_deps(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "pyproject.toml", '''
                [tool.poetry]
                name = "x"

                [tool.poetry.dependencies]
                python = "^3.10"
                requests = "^2.31"
            ''')
            mf = self.a.parse(tmp / "pyproject.toml")
            # `python` should be filtered out
            self.assertEqual([d.name for d in mf.deps], ["requests"])

    def test_used_in_source_dash_to_underscore(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "x.py", "import google_auth\n")
            files = [tmp / "x.py"]
            self.assertTrue(self.a.used_in_source("google-auth", files))
            self.assertFalse(self.a.used_in_source("absent", files))


# ─── go.mod adapter ──────────────────────────────────────────────────


class TestGoModAdapter(unittest.TestCase):
    def setUp(self):
        self.a = m.GoModAdapter()

    def test_parses_block_form(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "go.mod", '''
                module example.com/x

                go 1.21

                require (
                    github.com/foo/bar v1.0.0
                    github.com/baz/qux v0.5.0 // indirect
                )
            ''')
            mf = self.a.parse(tmp / "go.mod")
            names = {d.name for d in mf.deps}
            self.assertEqual(
                names, {"github.com/foo/bar", "github.com/baz/qux"},
            )


# ─── Orchestrator ────────────────────────────────────────────────────


class TestOrchestrator(unittest.TestCase):
    def test_audit_polyglot(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "Cargo.toml",
                   '[package]\nname = "x"\n\n[dependencies]\nserde = "1"\n')
            _write(tmp / "package.json",
                   json.dumps({"dependencies": {"react": "^18"}}))
            _write(tmp / "pyproject.toml",
                   '[project]\nname = "x"\ndependencies = ["requests"]\n')
            result = m.audit(tmp)
            self.assertEqual(
                set(result["languages"]),
                {"rust", "javascript", "python"},
            )
            self.assertEqual(result["total_deps"], 3)
            self.assertEqual(len(result["manifests"]), 3)

    def test_unused_detection_python(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "pyproject.toml",
                   '[project]\nname = "x"\n'
                   'dependencies = ["requests", "absent-dep"]\n')
            _write(tmp / "src" / "main.py", "import requests\n")
            result = m.unused(tmp)
            unused_names = {f["dep_name"] for f in result["unused"]}
            self.assertIn("absent-dep", unused_names)
            self.assertNotIn("requests", unused_names)

    def test_languages_present(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write(tmp / "go.mod", "module x\ngo 1.21\n")
            self.assertEqual(m.languages_present(tmp), ["go"])


# ─── MCP ─────────────────────────────────────────────────────────────


class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()


class TestManifestsMcp(_CwdMixin, unittest.TestCase):
    def _import(self):
        for mod in ("manifests_mcp", "_manifests"):
            if mod in sys.modules:
                del sys.modules[mod]
        import manifests_mcp
        return manifests_mcp

    def test_languages_tool(self):
        _write(self.tmp / "Cargo.toml", '[package]\nname = "x"\n')
        mcp = self._import()
        out = asyncio.run(mcp.manifests_languages())
        self.assertEqual(out, ["rust"])

    def test_audit_tool_returns_json_friendly(self):
        _write(self.tmp / "Cargo.toml",
               '[package]\nname = "x"\n\n[dependencies]\nserde = "1"\n')
        mcp = self._import()
        out = asyncio.run(mcp.manifests_audit())
        self.assertEqual(out["total_deps"], 1)
        # manifests is dicts, not dataclasses, after MCP conversion
        self.assertIsInstance(out["manifests"][0], dict)
        self.assertEqual(out["manifests"][0]["deps"][0]["name"], "serde")


class TestRegistration(unittest.TestCase):
    def test_manifests_in_mcp_json(self):
        data = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())
        # All domain servers are composed through the kaizen gateway
        self.assertIn("kaizen", data["mcpServers"])
        import gateway
        module_names = [m for _, m in gateway.SUBSERVERS]
        self.assertIn("manifests_mcp", module_names)


if __name__ == "__main__":
    unittest.main()
