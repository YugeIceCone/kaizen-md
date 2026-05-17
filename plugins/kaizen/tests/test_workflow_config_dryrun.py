"""TDD-RED for workflow_config.py `dry-run` subcommand.

Wires the per-rubric signal computer (loaded by path) + the rubric's
BucketWalker + the bucket_stage_skips map → emits an envelope so the
agent can preview WHICH schema stages would run before invoking the
real `run` subcommand.

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_workflow_config_dryrun -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills" / "workflow" / "scripts" / "workflow_config.py"


# ─── Test schema fixture ───────────────────────────────────────────────


_SCHEMA_YAML = """\
name: test-schema
version: 1
description: |
  Fixture schema for dry-run tests.

artifacts:
  - id: classify
    generates: classify/<task>.json
    template: null
    requires: []
    description: |
      Walk rubric.
    gate: |
      Bucket assigned.

  - id: red-test
    generates: tests
    template: null
    requires: [classify]
    description: red
    gate: red exit non-zero

  - id: green-impl
    generates: src
    template: null
    requires: [red-test]
    description: green
    gate: tests pass

apply:
  gate: green-impl
  progress: .kaizen/workflow/progress.md
  description: gated on green-impl
"""

_RUBRIC_YAML = """\
rules:
  - bucket: BUG_FIX
    require_all:
      - {signal: bug_keyword_count, op: ">=", value: 2}
  - bucket: DOC_ONLY
    require_all:
      - {signal: paths_doc_only, op: ">", value: 0}
      - {signal: paths_under_nodes, op: "==", value: 0}

confidence_threshold: 0.85
fallback: NEEDS_AGENT

bucket_stage_skips:
  BUG_FIX:
    skip: [classify]
    keep: [red-test, green-impl]
  DOC_ONLY:
    skip: [red-test, green-impl]
    keep: [classify]
  NEEDS_AGENT:
    skip: []
    keep: [classify, red-test, green-impl]
"""

_SIGNALS_PY = """\
import re
_BUG = re.compile(r"\\b(bug|fix|broken)\\b", re.IGNORECASE)
def compute_signals(prompt, touched_paths=None, created_dirs=None):
    paths = touched_paths or []
    return {
        "bug_keyword_count": len(_BUG.findall(prompt or "")),
        "paths_doc_only":    sum(1 for p in paths if p.endswith(".md")),
        "paths_under_nodes": sum(1 for p in paths if "/nodes/" in p and p.endswith(".rs")),
    }
"""


def _plant_schema(project_root: Path) -> None:
    """Plant a test-schema/ under <project_root>/.kaizen/workflow/schemas/."""
    sd = project_root / ".kaizen" / "workflow" / "schemas" / "test-schema"
    sd.mkdir(parents=True)
    (sd / "schema.yaml").write_text(_SCHEMA_YAML)
    (sd / "rubric.yaml").write_text(_RUBRIC_YAML)
    (sd / "_signals.py").write_text(_SIGNALS_PY)


def _run_dry(*args: str, project_root: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if project_root is not None:
        env["KAIZEN_PROJECT_ROOT_OVERRIDE"] = str(project_root)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "dry-run", *args],
        capture_output=True, text=True, env=env, timeout=10,
    )


class TestDryRunBucketClassification(unittest.TestCase):
    """dry-run picks the correct bucket given the prompt + paths."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        _plant_schema(self.project_root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bug_fix_bucket_on_bug_keywords(self):
        r = _run_dry(
            "--schema", "test-schema",
            "--prompt", "Fix the broken parser bug",
            "--json",
            project_root=self.project_root,
        )
        self.assertEqual(0, r.returncode, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["bucket"], "BUG_FIX")
        self.assertEqual(payload["method"], "deterministic")
        self.assertIn("red-test", payload["keep_stages"])
        self.assertIn("classify", payload["skip_stages"])

    def test_doc_only_bucket_on_md_paths(self):
        r = _run_dry(
            "--schema", "test-schema",
            "--prompt", "update the docs",
            "--paths", "docs/foo.md,README.md",
            "--json",
            project_root=self.project_root,
        )
        self.assertEqual(0, r.returncode, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["bucket"], "DOC_ONLY")
        self.assertIn("classify", payload["keep_stages"])
        self.assertIn("red-test", payload["skip_stages"])

    def test_fallback_needs_agent_on_no_match(self):
        r = _run_dry(
            "--schema", "test-schema",
            "--prompt", "",
            "--json",
            project_root=self.project_root,
        )
        self.assertEqual(0, r.returncode, r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["bucket"], "NEEDS_AGENT")
        self.assertEqual(payload["method"], "fallback")


class TestDryRunEnvelopeShape(unittest.TestCase):
    """dry-run output envelope contains the required fields."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        _plant_schema(self.project_root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_envelope_keys_present(self):
        r = _run_dry(
            "--schema", "test-schema",
            "--prompt", "fix bug broken",
            "--json",
            project_root=self.project_root,
        )
        payload = json.loads(r.stdout)
        for key in ("schema", "bucket", "method", "signals", "keep_stages", "skip_stages"):
            self.assertIn(key, payload, f"missing envelope key: {key}")

    def test_signals_dict_populated(self):
        r = _run_dry(
            "--schema", "test-schema",
            "--prompt", "fix broken",
            "--paths", "src/x.rs,docs/y.md",
            "--json",
            project_root=self.project_root,
        )
        payload = json.loads(r.stdout)
        self.assertIn("bug_keyword_count", payload["signals"])
        self.assertGreaterEqual(payload["signals"]["bug_keyword_count"], 2)
        self.assertEqual(payload["signals"]["paths_doc_only"], 1)


class TestDryRunErrors(unittest.TestCase):
    def test_unknown_schema_errors(self):
        r = _run_dry(
            "--schema", "nonexistent-schema-xyz",
            "--prompt", "hi",
        )
        self.assertNotEqual(0, r.returncode)
        self.assertIn("not found", r.stderr.lower() + r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
