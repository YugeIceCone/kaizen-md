"""Tests for detect_stack — mechanical stack detection.

Covers: artifact presence + parse-clean + behavior across 3 mini
projects (Rust, Python, JS) + hook wiring + freshness short-circuit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/util/detect_stack.py"
_HOOK = _KZ_DIR / "hooks/claude/session-start-detect-stack.sh"


def _run(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=15, cwd=cwd,
    )


class ProjectBase(unittest.TestCase):
    """Each test seeds a synthetic mini-project + runs detect."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestArtifact(unittest.TestCase):
    def test_script_present(self):
        self.assertTrue(_SCRIPT.is_file())

    def test_script_parses(self):
        with open(_SCRIPT) as f:
            compile(f.read(), str(_SCRIPT), "exec")

    def test_hook_present_and_executable(self):
        self.assertTrue(_HOOK.is_file())
        self.assertTrue(os.access(_HOOK, os.X_OK))

    def test_hook_wired_into_sessionstart(self):
        hooks_json = _KZ_DIR / "hooks/hooks.json"
        data = json.loads(hooks_json.read_text())
        ss = data["hooks"].get("SessionStart", [])
        cmds = [h["command"]
                for block in ss
                for h in block.get("hooks", [])]
        self.assertTrue(any("session-start-detect-stack" in c for c in cmds),
                          f"hook not wired: {cmds}")

    def test_permission_in_plugin_json(self):
        pj = _KZ_DIR / ".claude-plugin/plugin.json"
        allow = json.loads(pj.read_text())["permissions"]["allow"]
        self.assertTrue(any("session-start-detect-stack" in e for e in allow))
        self.assertTrue(any("detect_stack.py" in e for e in allow))


class TestRustProject(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "Cargo.toml").write_text(textwrap.dedent("""
            [package]
            name = "test-crate"
            edition = "2021"
            [dependencies]
            tokio = "1"
            axum = "0.7"
        """).strip())
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}")
        (self.root / "src" / "lib.rs").write_text("// lib")

    def test_detects_rust_with_edition(self):
        r = _run("scan", "--force", "--json", cwd=str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["primary"], "Rust")
        self.assertIn("Cargo.toml", data["manifests"])
        # Both artifacts emitted
        json_artifact = self.root / ".agents" / "stack-context.json"
        md_artifact = self.root / ".agents" / "stack-context.md"
        self.assertTrue(json_artifact.is_file())
        self.assertTrue(md_artifact.is_file())
        # JSON structure
        rec = json.loads(json_artifact.read_text())
        self.assertEqual(rec["schema_version"], 1)
        self.assertEqual(rec["stack"]["primary_language"], "Rust")
        self.assertEqual(rec["stack"]["language_version"], "Edition 2021")
        self.assertIn("axum", rec["stack"]["frameworks"])
        self.assertIn("tokio", rec["stack"]["frameworks"])
        # MD render
        body = md_artifact.read_text()
        self.assertIn("Edition 2021", body)
        self.assertIn("axum", body)
        self.assertIn("tokio", body)


class TestPythonProject(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "pyproject.toml").write_text(textwrap.dedent("""
            [project]
            name = "test"
            dependencies = ["fastapi", "httpx"]
            [tool.ruff]
            line-length = 100
            [tool.pytest.ini_options]
            testpaths = ["tests"]
        """).strip())
        (self.root / "main.py").write_text("# entry")

    def test_detects_python_with_frameworks(self):
        r = _run("scan", "--force", "--json", cwd=str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["primary"], "Python")
        body = (self.root / ".agents" / "stack-context.md").read_text()
        self.assertIn("fastapi", body)
        self.assertIn("pytest", body)


class TestFreshnessShortCircuit(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "Cargo.toml").write_text('[package]\nname = "x"\nedition = "2021"')
        (self.root / "src.rs").write_text("// rs")

    def test_first_run_writes_second_skips(self):
        r1 = _run("scan", "--json", cwd=str(self.root))
        self.assertEqual(r1.returncode, 0)
        self.assertNotIn("skipped", r1.stdout)
        r2 = _run("scan", "--json", cwd=str(self.root))
        self.assertIn("skipped", r2.stdout, r2.stdout)

    def test_force_overrides(self):
        _run("scan", "--json", cwd=str(self.root))
        r2 = _run("scan", "--force", "--json", cwd=str(self.root))
        self.assertNotIn("skipped", r2.stdout)


class TestSubcommands(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "go.mod").write_text("module test\n\ngo 1.21\n\nrequire github.com/gin-gonic/gin v1.9.1\n")
        (self.root / "main.go").write_text("package main")

    def test_path_prints_expected(self):
        r = _run("path", cwd=str(self.root))
        self.assertEqual(r.returncode, 0)
        # Path now points at the JSON (system of record); .md is derived.
        self.assertIn(".agents/stack-context.json", r.stdout)

    def test_show_fails_when_missing(self):
        r = _run("show", cwd=str(self.root))
        self.assertEqual(r.returncode, 1)

    def test_show_emits_artifact_after_scan(self):
        _run("scan", "--force", cwd=str(self.root))
        # Default `show` now emits JSON; grep for gin in either format.
        r = _run("show", cwd=str(self.root))
        self.assertEqual(r.returncode, 0)
        self.assertIn("gin", r.stdout.lower())
        # The JSON record has known keys
        parsed = json.loads(r.stdout)
        self.assertEqual(parsed["stack"]["primary_language"], "Go")
        # The md view (via --md) keeps the "# Stack Context" header
        r_md = _run("show", "--md", cwd=str(self.root))
        self.assertEqual(r_md.returncode, 0)
        self.assertIn("# Stack Context", r_md.stdout)

    def test_stale_returns_1_when_missing(self):
        r = _run("stale", cwd=str(self.root))
        self.assertEqual(r.returncode, 1)

    def test_stale_returns_0_after_scan(self):
        _run("scan", "--force", cwd=str(self.root))
        r = _run("stale", cwd=str(self.root))
        self.assertEqual(r.returncode, 0)


class TestSchemaValidation(ProjectBase):
    """The JSON artifact must validate against the shipped schema."""

    _SCHEMA = (_KZ_DIR / "assets/schemas/stack-context.schema.json")

    def setUp(self):
        super().setUp()
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "x"\nedition = "2021"\n[dependencies]\ntokio = "1"')
        (self.root / "main.rs").write_text("fn main() {}")

    def test_schema_file_present(self):
        self.assertTrue(self._SCHEMA.is_file())

    def test_artifact_validates_against_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents" / "stack-context.json").read_text())
        schema = json.loads(self._SCHEMA.read_text())
        jsonschema.validate(rec, schema)

    def test_show_default_emits_json(self):
        _run("scan", "--force", cwd=str(self.root))
        r = _run("show", cwd=str(self.root))
        self.assertEqual(r.returncode, 0)
        # Should be parseable as JSON
        parsed = json.loads(r.stdout)
        self.assertEqual(parsed["schema_version"], 1)

    def test_show_md_flag_emits_markdown(self):
        _run("scan", "--force", cwd=str(self.root))
        r = _run("show", "--md", cwd=str(self.root))
        self.assertEqual(r.returncode, 0)
        self.assertIn("# Stack Context", r.stdout)


class TestVersionPins(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "x"\nedition = "2021"')
        (self.root / "main.rs").write_text("fn main(){}")

    def test_rust_toolchain_file_detected(self):
        (self.root / "rust-toolchain").write_text("1.78.0\n")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("version_pins", rec)
        self.assertEqual(rec["version_pins"]["rust"], "1.78.0")
        self.assertIn("rust-toolchain", rec["version_pins"]["tool_versions_files"])

    def test_python_version_file_detected(self):
        (self.root / ".python-version").write_text("3.12.1\n")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("version_pins", rec)
        self.assertEqual(rec["version_pins"]["python"], "3.12.1")

    def test_tool_versions_multi_lang(self):
        (self.root / ".tool-versions").write_text(
            "# asdf\nnodejs 20.10.0\npython 3.12.1\n")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn(".tool-versions",
                       rec["version_pins"]["tool_versions_files"])


class TestContainerization(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "x"\nedition = "2021"')
        (self.root / "main.rs").write_text("fn main(){}")

    def test_dockerfile_detected(self):
        (self.root / "Dockerfile").write_text("FROM rust:1.78\n")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("containerization", rec)
        self.assertTrue(rec["containerization"]["dockerfile"])

    def test_compose_detected(self):
        (self.root / "docker-compose.yml").write_text("services:\n  web:\n    image: x\n")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("containerization", rec)
        self.assertTrue(rec["containerization"]["compose"])

    def test_no_container_signals(self):
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        # Block omitted when nothing detected (lean output)
        self.assertNotIn("containerization", rec)


class TestWorkspace(ProjectBase):
    def test_cargo_workspace_detected(self):
        (self.root / "Cargo.toml").write_text(
            '[workspace]\nmembers = ["foo", "bar", "baz"]\n')
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("workspace", rec)
        self.assertTrue(rec["workspace"]["is_workspace"])
        self.assertEqual(rec["workspace"]["kind"], "cargo")
        self.assertEqual(rec["workspace"]["member_count"], 3)

    def test_npm_workspace_detected(self):
        (self.root / "package.json").write_text(json.dumps({
            "name": "root",
            "workspaces": ["packages/a", "packages/b"],
        }))
        (self.root / "x.js").write_text("// x")
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("workspace", rec)
        self.assertEqual(rec["workspace"]["kind"], "npm")
        self.assertEqual(rec["workspace"]["member_count"], 2)


class TestPreCommit(ProjectBase):
    def setUp(self):
        super().setUp()
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "x"\nedition = "2021"')
        (self.root / "main.rs").write_text("fn main(){}")

    def test_pre_commit_config_with_hooks_counted(self):
        (self.root / ".pre-commit-config.yaml").write_text(textwrap.dedent("""
            repos:
              - repo: https://github.com/astral-sh/ruff-pre-commit
                rev: v0.5.0
                hooks:
                  - id: ruff
                  - id: ruff-format
              - repo: https://github.com/pre-commit/pre-commit-hooks
                rev: v4.4.0
                hooks:
                  - id: trailing-whitespace
        """).strip())
        _run("scan", "--force", cwd=str(self.root))
        rec = json.loads((self.root / ".agents/stack-context.json").read_text())
        self.assertIn("pre_commit", rec)
        self.assertTrue(rec["pre_commit"]["config_present"])
        self.assertEqual(rec["pre_commit"]["hook_count"], 3)


class TestSelfValidate(ProjectBase):
    """`scan` self-validates the emitted record against the shipped
    schema. Catches drift if anyone changes _build_record without
    updating the schema."""

    def test_real_scan_validates_against_schema(self):
        (self.root / "go.mod").write_text("module x\n\ngo 1.21\n")
        (self.root / "main.go").write_text("package main")
        r = _run("scan", "--force", cwd=str(self.root))
        self.assertEqual(r.returncode, 0)
        # No WARN line on stderr — _self_validate passed
        self.assertNotIn("failed schema validation", r.stderr)


class TestHookBehavior(ProjectBase):
    def _fire(self, cwd: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["KAIZEN_PLUGIN_ROOT"] = str(_KZ_DIR)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", str(_HOOK)],
            input='{"session_id": "test"}',
            capture_output=True, text=True, timeout=10,
            cwd=cwd, env=env,
        )

    def test_disabled_emits_empty_json(self):
        r = self._fire(str(self.root),
                       env_extra={"KAIZEN_DETECT_STACK_DISABLE": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "{}")

    def test_runs_detect_when_artifact_missing(self):
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "x"\nedition = "2021"')
        (self.root / "src.rs").write_text("// rs")
        r = self._fire(str(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        # Both artifacts should have been generated by the hook
        self.assertTrue((self.root / ".agents" / "stack-context.json").is_file())
        self.assertTrue((self.root / ".agents" / "stack-context.md").is_file())
        if r.stdout.strip() and r.stdout.strip() != "{}":
            out = json.loads(r.stdout)
            self.assertIn("additionalContext", out)
            self.assertIn("Stack Context", out["additionalContext"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
