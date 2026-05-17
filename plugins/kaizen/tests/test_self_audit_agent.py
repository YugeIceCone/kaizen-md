"""Tests for self_audit_agent.py — the agent-driven follow-up audit.

Three layers:
- pure logic (build_briefs / _validate_result / merge_results / _latest_run_id)
- aggregate flow against hand-crafted manifest + result files (sandboxed)
- dispatch-plan integration (runs the real mechanical audit; PyYAML-gated)

All disk writes are sandboxed via KAIZEN_SELF_AUDIT_AGENT_DIR.
"""

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
import self_audit_agent as agent  # noqa: E402


def _checkpoint(cid: str, skill: str, targets=None, rationale="focus here"):
    """A checkpoint Finding shaped like self_audit emits (to_dict form)."""
    return {
        "id": cid, "stage": cid, "kind": "checkpoint", "severity": "medium",
        "title": f"agent-checkpoint: load Skill({skill})",
        "detail": "", "files": targets or [], "skill": skill,
        "rationale": rationale, "remediation": "apply it",
    }


class SandboxBase(unittest.TestCase):
    """Sandboxes the agent-audit dir so tests never touch the real repo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "agent-audits"
        self._orig = os.environ.get("KAIZEN_SELF_AUDIT_AGENT_DIR")
        os.environ["KAIZEN_SELF_AUDIT_AGENT_DIR"] = str(self.root)

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_SELF_AUDIT_AGENT_DIR", None)
        else:
            os.environ["KAIZEN_SELF_AUDIT_AGENT_DIR"] = self._orig


class TestModuleAndConfig(unittest.TestCase):
    def test_module_parses(self):
        path = _KZ_DIR / "skills/workflow/scripts/self_audit_agent.py"
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_dispatch_config_loads(self):
        try:
            cfg = _self_audit.load_agent_dispatch()
        except RuntimeError:
            self.skipTest("PyYAML not installed")
        self.assertIn("prompt_template", cfg)
        self.assertIn("{skill}", cfg["prompt_template"])
        self.assertEqual(cfg["dispatch"]["subagent_type"], "general-purpose")

    def test_checkpoint_result_schema_valid(self):
        schema = json.loads(agent._RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["required"], ["checkpoint_id", "skill", "status", "findings"])
        self.assertFalse(schema["additionalProperties"])

    def test_agent_audit_dir_env_override(self):
        orig = os.environ.get("KAIZEN_SELF_AUDIT_AGENT_DIR")
        os.environ["KAIZEN_SELF_AUDIT_AGENT_DIR"] = "/tmp/kz-agent-test-xyz"
        try:
            self.assertEqual(
                str(_self_audit.agent_audit_dir()), "/tmp/kz-agent-test-xyz")
        finally:
            if orig is None:
                os.environ.pop("KAIZEN_SELF_AUDIT_AGENT_DIR", None)
            else:
                os.environ["KAIZEN_SELF_AUDIT_AGENT_DIR"] = orig


class TestBuildBriefs(unittest.TestCase):
    def setUp(self):
        try:
            self.cfg = _self_audit.load_agent_dispatch()
        except RuntimeError:
            self.skipTest("PyYAML not installed")
        self.schema_text = agent._RESULT_SCHEMA_PATH.read_text(encoding="utf-8")
        self.run_dir = Path("/tmp/kz-run")

    def test_brief_is_self_contained(self):
        cps = [_checkpoint("kiss-cp", "kiss", ["plugins/kaizen/scripts/"])]
        briefs = agent.build_briefs(cps, self.cfg, self.schema_text, self.run_dir)
        self.assertEqual(len(briefs), 1)
        b = briefs[0]
        self.assertEqual(b["checkpoint_id"], "kiss-cp")
        self.assertEqual(b["skill"], "kiss")
        self.assertEqual(b["subagent_type"], "general-purpose")
        # No unsubstituted placeholders survive into the prompt.
        for ph in ("{skill}", "{targets_block}", "{rationale}",
                   "{result_path}", "{result_schema}"):
            self.assertNotIn(ph, b["prompt"])
        # The prompt actually carries the substituted values.
        self.assertIn("kiss", b["prompt"])
        self.assertIn("plugins/kaizen/scripts/", b["prompt"])
        self.assertIn(b["result_path"], b["prompt"])
        self.assertIn("kiss-cp.json", b["result_path"])

    def test_brief_no_targets(self):
        cps = [_checkpoint("x-cp", "yagni", [])]
        briefs = agent.build_briefs(cps, self.cfg, self.schema_text, self.run_dir)
        self.assertIn("no targets declared", briefs[0]["prompt"])

    def test_brief_includes_severity_hint(self):
        cps = [_checkpoint("s-cp", "solid", ["x/"])]
        briefs = agent.build_briefs(cps, self.cfg, self.schema_text, self.run_dir)
        # severity_hint is appended into the rationale region.
        self.assertIn("Severity guidance", briefs[0]["prompt"])

    def test_per_checkpoint_subagent_type_override(self):
        cp = _checkpoint("o-cp", "onion-ddd-workflow", ["x/"])
        cp["subagent_type"] = "Explore"
        briefs = agent.build_briefs([cp], self.cfg, self.schema_text, self.run_dir)
        self.assertEqual(briefs[0]["subagent_type"], "Explore")

    def test_prompt_schema_strips_meta_keys(self):
        # The schema embedded in a brief must not carry its own
        # meta-keys — subagents copy them into their result, which
        # additionalProperties:false then rejects.
        cleaned = json.loads(agent._prompt_schema(self.schema_text))
        for meta in ("$schema", "$id", "title", "description"):
            self.assertNotIn(meta, cleaned)
        # the substantive contract survives the strip
        self.assertEqual(cleaned["required"],
                         ["checkpoint_id", "skill", "status", "findings"])
        self.assertFalse(cleaned["additionalProperties"])

    def test_brief_embeds_no_schema_meta_keys(self):
        cps = [_checkpoint("k-cp", "kiss", ["x/"])]
        briefs = agent.build_briefs(cps, self.cfg, self.schema_text, self.run_dir)
        self.assertNotIn('"$schema"', briefs[0]["prompt"])
        self.assertNotIn('"$id"', briefs[0]["prompt"])


class TestValidateResult(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            agent._RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _ok(self):
        return {"checkpoint_id": "c", "skill": "kiss", "status": "clean",
                "findings": []}

    def test_valid_passes(self):
        self.assertIsNone(agent._validate_result(self._ok(), self.schema))

    def test_missing_key_fails(self):
        bad = self._ok()
        del bad["status"]
        self.assertIsNotNone(agent._validate_result(bad, self.schema))

    def test_bad_status_fails(self):
        bad = self._ok()
        bad["status"] = "weird"
        self.assertIsNotNone(agent._validate_result(bad, self.schema))

    def test_findings_not_list_fails(self):
        bad = self._ok()
        bad["findings"] = "nope"
        self.assertIsNotNone(agent._validate_result(bad, self.schema))

    def test_structural_fallback_without_schema(self):
        # schema=None forces the no-jsonschema structural path.
        self.assertIsNone(agent._validate_result(self._ok(), None))
        bad = self._ok()
        del bad["skill"]
        self.assertIsNotNone(agent._validate_result(bad, None))

    def test_meta_keys_tolerated(self):
        # Subagents echo $schema/$id from the schema embedded in their
        # brief — these must NOT fail validation (the prompt bug the
        # first live agent-self-audit run surfaced). Both the
        # jsonschema path and the structural fallback strip them.
        ok = self._ok()
        ok["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        ok["$id"] = "https://example/x.json"
        self.assertIsNone(agent._validate_result(ok, self.schema))
        self.assertIsNone(agent._validate_result(ok, None))


class TestMergeResults(unittest.TestCase):
    def _brief(self, cid, skill):
        return {"checkpoint_id": cid, "skill": skill, "targets": [],
                "subagent_type": "general-purpose",
                "result_path": f"/tmp/{cid}.json", "prompt": "..."}

    def test_missing_file_becomes_medium_finding(self):
        briefs = [self._brief("c1", "kiss")]
        collected = [{"brief": briefs[0], "raw": None,
                      "read_error": "result file not written"}]
        merged = agent.merge_results(briefs, collected)
        self.assertEqual(len(merged["findings"]), 1)
        self.assertEqual(merged["findings"][0].severity, "medium")
        self.assertIn("missing", merged["findings"][0].title)
        self.assertEqual(merged["checkpoints"][0]["status"], "missing")

    def test_malformed_result_becomes_medium_finding(self):
        briefs = [self._brief("c2", "dry")]
        collected = [{"brief": briefs[0],
                      "raw": {"checkpoint_id": "c2"},  # missing keys
                      "read_error": None}]
        merged = agent.merge_results(briefs, collected)
        self.assertEqual(merged["findings"][0].severity, "medium")
        self.assertIn("malformed", merged["findings"][0].title)

    def test_clean_result_yields_no_findings(self):
        briefs = [self._brief("c3", "yagni")]
        collected = [{"brief": briefs[0], "raw": {
            "checkpoint_id": "c3", "skill": "yagni", "status": "clean",
            "findings": [], "summary": "all good"}, "read_error": None}]
        merged = agent.merge_results(briefs, collected)
        self.assertEqual(merged["findings"], [])
        self.assertEqual(merged["checkpoints"][0]["status"], "clean")
        self.assertEqual(merged["checkpoints"][0]["summary"], "all good")

    def test_error_status_becomes_medium_finding(self):
        briefs = [self._brief("c4", "solid")]
        collected = [{"brief": briefs[0], "raw": {
            "checkpoint_id": "c4", "skill": "solid", "status": "error",
            "findings": [], "summary": "could not read targets"},
            "read_error": None}]
        merged = agent.merge_results(briefs, collected)
        self.assertEqual(merged["findings"][0].severity, "medium")
        self.assertIn("errored", merged["findings"][0].title)

    def test_findings_are_flattened_and_sorted(self):
        briefs = [self._brief("c5", "kiss")]
        collected = [{"brief": briefs[0], "raw": {
            "checkpoint_id": "c5", "skill": "kiss", "status": "findings",
            "summary": "2 issues",
            "findings": [
                {"severity": "low", "title": "minor nit here",
                 "files": ["a.py"]},
                {"severity": "high", "title": "big structural problem",
                 "files": ["b.py"], "remediation": "split it"},
            ]}, "read_error": None}]
        merged = agent.merge_results(briefs, collected)
        self.assertEqual(len(merged["findings"]), 2)
        # high sorts before low
        self.assertEqual(merged["findings"][0].severity, "high")
        self.assertEqual(merged["findings"][0].skill, "kiss")
        self.assertEqual(merged["checkpoints"][0]["finding_count"], 2)

    def test_dedup_by_id(self):
        briefs = [self._brief("c6", "kiss")]
        dup = {"severity": "low", "title": "same title"}
        collected = [{"brief": briefs[0], "raw": {
            "checkpoint_id": "c6", "skill": "kiss", "status": "findings",
            "findings": [dup, dict(dup)]}, "read_error": None}]
        merged = agent.merge_results(briefs, collected)
        self.assertEqual(len(merged["findings"]), 1)


class TestAggregateFlow(SandboxBase):
    """End-to-end aggregate against a hand-crafted run dir."""

    def _seed_run(self, run_id="2026-01-01T00-00-00Z"):
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True)
        briefs = [
            {"checkpoint_id": "kiss-cp", "skill": "kiss", "targets": [],
             "subagent_type": "general-purpose",
             "result_path": str(run_dir / "kiss-cp.json"), "prompt": "..."},
            {"checkpoint_id": "dry-cp", "skill": "dry", "targets": [],
             "subagent_type": "general-purpose",
             "result_path": str(run_dir / "dry-cp.json"), "prompt": "..."},
        ]
        (run_dir / "dispatch.json").write_text(json.dumps({
            "run_id": run_id, "generated_at": "2026-01-01T00:00:00+00:00",
            "subagent_type": "general-purpose", "max_parallel": 5,
            "checkpoint_count": 2, "briefs": briefs,
        }), encoding="utf-8")
        # kiss result present + has a finding; dry result deliberately absent.
        (run_dir / "kiss-cp.json").write_text(json.dumps({
            "checkpoint_id": "kiss-cp", "skill": "kiss", "status": "findings",
            "summary": "one nit", "findings": [
                {"severity": "medium", "title": "over-abstracted helper",
                 "files": ["x.py"], "remediation": "inline it"}]}),
            encoding="utf-8")
        return run_id

    def test_aggregate_merges_and_writes_report(self):
        run_id = self._seed_run()
        result = agent.run_aggregate(run_id=run_id)
        self.assertNotIn("error", result)
        # kiss finding + dry missing-result finding
        self.assertEqual(result["finding_count"], 2)
        path = Path(result["report_path"])
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("agent-self-audit", text)
        self.assertIn("over-abstracted helper", text)
        self.assertIn("Remediation plan", text)

    def test_aggregate_latest_run_when_no_id(self):
        self._seed_run("2026-01-01T00-00-00Z")
        newer = self._seed_run("2026-02-02T00-00-00Z")
        result = agent.run_aggregate(run_id=None)
        self.assertEqual(result["run_id"], newer)

    def test_aggregate_no_runs_returns_error(self):
        result = agent.run_aggregate(run_id=None)
        self.assertIn("error", result)

    def test_latest_run_id_picks_max(self):
        (self.root / "2026-01-01T00-00-00Z").mkdir(parents=True)
        (self.root / "2026-03-03T00-00-00Z").mkdir(parents=True)
        self.assertEqual(agent._latest_run_id(), "2026-03-03T00-00-00Z")


class TestDispatchPlanIntegration(SandboxBase):
    """Runs the real mechanical audit — PyYAML-gated, slower."""

    def test_dispatch_plan_writes_manifest(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        result = agent.run_dispatch_plan()
        self.assertIn("run_id", result)
        manifest_path = Path(result["manifest_path"])
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_id"], result["run_id"])
        self.assertEqual(manifest["checkpoint_count"], len(manifest["briefs"]))
        # The mechanical pipeline declares skill checkpoints, so the
        # dispatch plan should carry briefs for them.
        self.assertGreater(manifest["checkpoint_count"], 0)
        for b in manifest["briefs"]:
            self.assertIn("prompt", b)
            self.assertIn("result_path", b)
            self.assertNotIn("{skill}", b["prompt"])


class TestCli(SandboxBase):
    def _run(self, *args):
        script = _KZ_DIR / "skills/workflow/scripts/self_audit_agent.py"
        return subprocess.run(
            ["python3", str(script), *args],
            capture_output=True, text=True, timeout=90,
            env={**os.environ},
        )

    def test_path_subcommand(self):
        result = self._run("path")
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        self.assertIn("agent_audit_dir", out)
        self.assertIn("dispatch_config", out)

    def test_aggregate_no_run_exits_1(self):
        result = self._run("aggregate", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
