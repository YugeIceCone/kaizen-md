"""Tests for self_audit.py — schema-driven plugin self-audit pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _self_audit  # noqa: E402
import self_audit  # noqa: E402
from _self_audit import Finding  # noqa: E402


class TestPipelineLoad(unittest.TestCase):
    def test_pipeline_yaml_loads(self):
        try:
            data = _self_audit.load_pipeline()
        except RuntimeError:
            self.skipTest("PyYAML not installed")
        self.assertIn("stages", data)
        self.assertGreater(len(data["stages"]), 5)

    def test_pipeline_has_expected_stages(self):
        try:
            data = _self_audit.load_pipeline()
        except RuntimeError:
            self.skipTest("PyYAML not installed")
        ids = [s.get("id") for s in data["stages"] if isinstance(s, dict)]
        for required in (
            "validator",
            "metrics-coverage",
            "metrics-skips",
            "hook-trace-coverage",
            "bin-permission-coverage",
            "onion-ddd-checkpoint",
            "kiss-checkpoint",
            "dry-checkpoint",
            "yagni-checkpoint",
            "solid-checkpoint",
            "karpathy-checkpoint",
            "verification-before-completion-checkpoint",
            "writing-plans-checkpoint",
            "executing-plans-checkpoint",
        ):
            self.assertIn(required, ids, f"missing stage: {required}")


class TestFindingDataclass(unittest.TestCase):
    def test_make_id_stable(self):
        a = Finding.make_id("stage", "key")
        b = Finding.make_id("stage", "key")
        self.assertEqual(a, b)

    def test_make_id_distinct(self):
        a = Finding.make_id("stage", "key1")
        b = Finding.make_id("stage", "key2")
        self.assertNotEqual(a, b)

    def test_to_dict_round_trip(self):
        f = Finding(
            id="x", stage="s", kind="mechanical",
            severity="medium", title="T", detail="D",
        )
        d = f.to_dict()
        self.assertEqual(d["id"], "x")
        self.assertEqual(d["severity"], "medium")


class TestRunners(unittest.TestCase):
    """Each runner is callable + returns a list of Findings (possibly empty)."""

    def test_run_validator(self):
        try:
            findings = self_audit.run_validator({"id": "validator"})
        except Exception as e:
            self.fail(f"run_validator raised: {e}")
        self.assertIsInstance(findings, list)
        for f in findings:
            self.assertIsInstance(f, Finding)

    def test_run_metrics_coverage(self):
        findings = self_audit.run_metrics_coverage({"id": "metrics-coverage"})
        self.assertIsInstance(findings, list)

    def test_run_hook_trace_check(self):
        findings = self_audit.run_hook_trace_check(
            {"id": "hook-trace-coverage"})
        self.assertIsInstance(findings, list)
        # Every finding has the right shape
        for f in findings:
            self.assertEqual(f.kind, "mechanical")
            self.assertEqual(f.stage, "hook-trace-coverage")

    def test_run_bin_permission_check(self):
        findings = self_audit.run_bin_permission_check(
            {"id": "bin-permission-coverage"})
        self.assertIsInstance(findings, list)

    def test_run_vendored_check(self):
        findings = self_audit.run_vendored_check({"id": "vendored"})
        self.assertIsInstance(findings, list)


class TestSkillCheckpointEmit(unittest.TestCase):
    def test_emit_skill_checkpoint(self):
        stage = {
            "id": "kiss-checkpoint",
            "skill": "kiss",
            "description": "load + apply kiss",
            "rationale": "explanation",
            "targets": ["plugins/kaizen/"],
        }
        f = self_audit.emit_skill_checkpoint(stage)
        self.assertEqual(f.kind, "checkpoint")
        self.assertEqual(f.skill, "kiss")
        self.assertIn("plugins/kaizen/", f.files)


class TestEndToEndAudit(unittest.TestCase):
    def test_full_audit_no_write(self):
        try:
            result = self_audit.run_audit(no_write=True)
        except RuntimeError as e:
            if "PyYAML" in str(e):
                self.skipTest("PyYAML not installed")
            raise
        # Result has expected keys
        self.assertIn("finding_count", result)
        self.assertIn("remediation_task_count", result)
        self.assertIn("new_functionality_count", result)
        self.assertIn("findings", result)
        self.assertIn("markdown", result)
        # Has at least the skill-checkpoint findings
        self.assertGreater(result["finding_count"], 5)

    def test_audit_writes_report(self):
        try:
            result = self_audit.run_audit(no_write=False)
        except RuntimeError as e:
            if "PyYAML" in str(e):
                self.skipTest("PyYAML not installed")
            raise
        path = Path(result["report_path"])
        self.assertTrue(path.is_file())
        text = path.read_text()
        self.assertIn("kaizen self-audit", text)
        # Cleanup
        path.unlink()

    def test_markdown_has_canonical_sections(self):
        try:
            result = self_audit.run_audit(no_write=True)
        except RuntimeError as e:
            if "PyYAML" in str(e):
                self.skipTest("PyYAML not installed")
            raise
        md = result["markdown"]
        for section in (
            "Executive summary",
            "Skill checkpoints",
        ):
            self.assertIn(section, md)


class TestCli(unittest.TestCase):
    def _run(self, *args):
        script = _KZ_DIR / "skills/workflow/scripts/self_audit.py"
        return subprocess.run(
            ["python3", str(script), *args],
            capture_output=True, text=True, timeout=60,
        )

    def test_path_subcommand(self):
        result = self._run("path")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertIn("report_dir", out["data"])
        self.assertIn("pipeline", out["data"])

    def test_list_stages_subcommand(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        result = self._run("list-stages")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertGreater(len(out["data"]), 5)

    def test_run_subcommand_no_write(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        result = self._run("run", "--no-write", "--json")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertIn("finding_count", out["data"])

    def test_bare_invocation_runs(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        result = self._run()  # no subcommand
        self.assertEqual(result.returncode, 0)
        # Bare invocation defaults to --no-write=False; might create a report
        # but exits 0
        self.assertIn("kaizen self-audit", result.stdout)
        # Cleanup any report it wrote
        for p in (_self_audit.REPO_ROOT / ".kaizen" / "audits").glob("*-self.md"):
            try:
                p.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
