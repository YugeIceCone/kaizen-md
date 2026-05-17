"""Tests for the plugin-development workflow schema + slash command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCHEMA = _KZ_DIR / "schemas/plugin-development/schema.yaml"
_COMMAND = _KZ_DIR / "commands/plugin-development.md"
_WORKFLOW_RUNNER = _KZ_DIR / "skills/workflow/scripts/workflow_runner.py"


class TestSchemaArtifact(unittest.TestCase):
    def test_schema_file_present(self):
        self.assertTrue(_SCHEMA.is_file(),
                         "plugins/kaizen/schemas/plugin-development/schema.yaml missing")

    def test_schema_loads_as_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        data = yaml.safe_load(_SCHEMA.read_text())
        self.assertEqual(data["name"], "plugin-development")
        self.assertEqual(data["version"], 1)
        self.assertGreaterEqual(len(data["artifacts"]), 8,
                                  "expected ≥8 stages (scope→document)")
        artifact_ids = [a["id"] for a in data["artifacts"]]
        expected_stages = {"scope", "scaffold", "wire", "red",
                            "green", "refactor", "validate", "document"}
        self.assertEqual(set(artifact_ids), expected_stages,
                          f"stages drift: got {artifact_ids}")

    def test_dependency_dag_is_linear(self):
        """Stages must form a linear chain — each artifact requires
        the previous one. Catches accidental DAG drift."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        data = yaml.safe_load(_SCHEMA.read_text())
        artifacts = {a["id"]: a for a in data["artifacts"]}
        # scope has no requires
        self.assertEqual(artifacts["scope"].get("requires", []), [])
        # Every other stage requires exactly one predecessor
        chain = ["scope", "scaffold", "wire", "red", "green",
                  "refactor", "validate", "document"]
        for i in range(1, len(chain)):
            prev, curr = chain[i - 1], chain[i]
            requires = artifacts[curr].get("requires", [])
            self.assertEqual(requires, [prev],
                              f"{curr} should require [{prev}], got {requires}")

    def test_gate_is_validate(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        data = yaml.safe_load(_SCHEMA.read_text())
        self.assertEqual(data["apply"]["gate"], "validate",
                          "the apply-gate must be the validate stage")


class TestWorkflowRunnerDiscovers(unittest.TestCase):
    def test_schema_in_list(self):
        r = subprocess.run([sys.executable, str(_WORKFLOW_RUNNER), "list"],
                            capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("plugin-development", r.stdout,
                        "workflow_runner list must surface the new schema")


class TestSlashCommandShape(unittest.TestCase):
    def test_command_file_present(self):
        self.assertTrue(_COMMAND.is_file())

    def test_command_frontmatter_lists_verbs(self):
        text = _COMMAND.read_text()
        for verb in ("workflow", "validate", "rules"):
            self.assertIn(verb, text, f"verb {verb!r} must appear in command body")

    def test_command_routes_via_case(self):
        text = _COMMAND.read_text()
        self.assertIn("case \"$ARGS\" in", text,
                       "command body must dispatch verbs via bash case")
        # Each verb branch must be present
        for branch in ("workflow|workflow", "validate|validate", "rules|rules"):
            self.assertIn(branch, text,
                            f"missing case branch for {branch}")


class TestHelpGenClusterIncludesIt(unittest.TestCase):
    def test_plugin_development_in_clusters(self):
        helpgen_py = _KZ_DIR / "skills/workflow/scripts/help_gen.py"
        text = helpgen_py.read_text()
        self.assertIn("plugin-development", text,
                       "help_gen.py CLUSTERS must list plugin-development")


if __name__ == "__main__":
    unittest.main(verbosity=2)
