"""Unit tests for workflow_config.py — the persistent workflow-shape
config CLI (project / global). Sandboxes via KAIZEN_WORKFLOW_CONFIG_PATH
and KAIZEN_WORKFLOW_GLOBAL_CONFIG_PATH so the real ~/.claude/ is never
touched.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the scripts dir importable.
_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import workflow_config as wc  # noqa: E402


class _Sandbox(unittest.TestCase):
    """Each test gets its own tempdir + isolated env."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name) / "proj" / ".kaizen" / "workflow.json"
        self.glob = Path(self.tmp.name) / "global" / "workflow-global.json"
        self._orig_env = dict(os.environ)
        os.environ["KAIZEN_WORKFLOW_CONFIG_PATH"] = str(self.proj)
        os.environ["KAIZEN_WORKFLOW_GLOBAL_CONFIG_PATH"] = str(self.glob)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        self.tmp.cleanup()


class TestRoundTrip(_Sandbox):
    def test_set_then_get_project(self):
        rc = wc.main([
            "set", "--scope", "project",
            "--run-mode", "loop",
            "--disciplines", "kiss,dry,tdd",
            "--threshold", "75",
            "--loop-its", "30",
            "--loop-stop", "promise,iteration-cap",
        ])
        self.assertEqual(rc, 0)
        self.assertTrue(self.proj.exists())

        data = json.loads(self.proj.read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["scope"], "project")
        self.assertEqual(data["run_mode"], "loop")
        self.assertEqual(data["disciplines"], ["kiss", "dry", "tdd"])
        self.assertEqual(data["auto_handoff_threshold"], 75)
        self.assertEqual(data["loop"]["max_iterations"], 30)
        self.assertEqual(
            data["loop"]["stop_conditions"], ["promise", "iteration-cap"]
        )
        self.assertIn("updated_at", data)

    def test_set_then_get_global(self):
        rc = wc.main([
            "set", "--scope", "global",
            "--run-mode", "routine",
            "--routine", "build-feature",
            "--threshold", "85",
        ])
        self.assertEqual(rc, 0)
        self.assertTrue(self.glob.exists())
        data = json.loads(self.glob.read_text())
        self.assertEqual(data["scope"], "global")
        self.assertEqual(data["routine"], "build-feature")
        self.assertEqual(data["auto_handoff_threshold"], 85)

    def test_threshold_disabled_writes_null(self):
        wc.main(["set", "--threshold", "disabled"])
        data = json.loads(self.proj.read_text())
        self.assertIsNone(data["auto_handoff_threshold"])

    def test_partial_set_preserves_existing(self):
        wc.main(["set", "--run-mode", "routine", "--disciplines", "kiss"])
        wc.main(["set", "--threshold", "50"])  # only threshold
        data = json.loads(self.proj.read_text())
        self.assertEqual(data["run_mode"], "routine")
        self.assertEqual(data["disciplines"], ["kiss"])
        self.assertEqual(data["auto_handoff_threshold"], 50)


class TestValidation(_Sandbox):
    def test_invalid_run_mode_exits(self):
        with self.assertRaises(SystemExit):
            wc.main(["set", "--run-mode", "bogus"])

    def test_invalid_discipline_exits(self):
        with self.assertRaises(SystemExit):
            wc.main(["set", "--disciplines", "kiss,nope"])

    def test_invalid_threshold_exits(self):
        with self.assertRaises(SystemExit):
            wc.main(["set", "--threshold", "100"])

    def test_invalid_threshold_string_exits(self):
        with self.assertRaises(SystemExit):
            wc.main(["set", "--threshold", "abc"])

    def test_invalid_loop_stop_exits(self):
        with self.assertRaises(SystemExit):
            wc.main(["set", "--loop-stop", "promise,nope"])

    def test_invalid_loop_its_exits(self):
        with self.assertRaises(SystemExit):
            wc.main(["set", "--loop-its", "0"])


class TestMergedRead(_Sandbox):
    """get / show with no --scope merges project on top of global."""

    def test_project_overrides_global(self):
        wc.main(["set", "--scope", "global", "--threshold", "85"])
        wc.main(["set", "--scope", "project", "--threshold", "50"])
        merged = wc._merged()
        self.assertEqual(merged["auto_handoff_threshold"], 50)

    def test_global_fills_missing_project_fields(self):
        wc.main(["set", "--scope", "global", "--disciplines", "kiss"])
        wc.main(["set", "--scope", "project", "--threshold", "75"])
        merged = wc._merged()
        self.assertEqual(merged["disciplines"], ["kiss"])
        self.assertEqual(merged["auto_handoff_threshold"], 75)


class TestReset(_Sandbox):
    def test_reset_dry_run_keeps_file(self):
        wc.main(["set", "--threshold", "75"])
        rc = wc.main(["reset"])
        self.assertEqual(rc, 1)
        self.assertTrue(self.proj.exists())

    def test_reset_yes_deletes_file(self):
        wc.main(["set", "--threshold", "75"])
        rc = wc.main(["reset", "--yes"])
        self.assertEqual(rc, 0)
        self.assertFalse(self.proj.exists())

    def test_reset_missing_file_returns_0(self):
        rc = wc.main(["reset"])
        self.assertEqual(rc, 0)


class TestPath(_Sandbox):
    def test_path_project(self):
        # Path subcommand prints; capture via stdout redirect would
        # need extra plumbing — just verify it returns 0.
        self.assertEqual(wc.main(["path"]), 0)
        self.assertEqual(wc.main(["path", "--scope", "global"]), 0)


class TestSchemaValidity(unittest.TestCase):
    """The shipped JSON Schema must be valid JSON + declare version."""

    def test_schema_exists_and_parses(self):
        schema_path = (
            _KZ_DIR / "skills/workflow/domain/schemas/workflow-config.schema.json"
        )
        self.assertTrue(schema_path.is_file())
        data = json.loads(schema_path.read_text())
        self.assertEqual(data["title"], "kaizen workflow-config")
        self.assertIn("version", data["required"])

    def test_schema_enumerates_thresholds_25_50_75_85(self):
        schema_path = (
            _KZ_DIR / "skills/workflow/domain/schemas/workflow-config.schema.json"
        )
        data = json.loads(schema_path.read_text())
        thr = data["properties"]["auto_handoff_threshold"]["anyOf"][0]["enum"]
        self.assertEqual(thr, [25, 50, 75, 85])


if __name__ == "__main__":
    unittest.main(verbosity=2)
