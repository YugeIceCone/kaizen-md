"""Tests for handoff.py::create — structured-input one-shot handoff write.

`create` accepts a typed JSON payload (via --stdin or --data-file),
validates against the create-in schema, generates valid YAML, writes
to the canonical path, indexes into the DB. Replaces the agent's
Steps 1+2+3 (session-name derivation + Write tool + Bash save).
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
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_HANDOFF_PY = _SCRIPTS / "handoff.py"
_DOMAIN = _KZ_DIR / "skills/handoff/domain"


_SAMPLE = {
    "session": "demo",
    "goal": "test the create subcommand",
    "now": "verify the YAML",
    "test": "python3 -m unittest tests.test_handoff_create",
    "done_this_session": [{"task": "wrote tests", "files": ["tests/test_x.py"]}],
    "blockers": [],
    "questions": [],
    "decisions": [],
    "findings": [],
    "worked": [],
    "failed": [],
    "next": ["implement create"],
    "files": {"created": ["tests/test_x.py"], "modified": []},
    "at": "2026-05-17_04-00",
    "description_slug": "test-create",
}


class CreateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.handoffs_dir = self.tmp / "handoffs"
        self.handoffs_dir.mkdir()
        self._orig_dir = os.environ.get("KAIZEN_HANDOFF_DIR")
        self._orig_db = os.environ.get("KAIZEN_HANDOFF_DB")
        os.environ["KAIZEN_HANDOFF_DIR"] = str(self.handoffs_dir)
        os.environ["KAIZEN_HANDOFF_DB"] = str(self.tmp / "handoff.db")

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_HANDOFF_DIR", self._orig_dir),
                          ("KAIZEN_HANDOFF_DB", self._orig_db)):
            if orig is None: os.environ.pop(var, None)
            else: os.environ[var] = orig

    def _run(self, payload: dict, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "create", "--stdin", "--json", *extra],
            input=json.dumps(payload), capture_output=True, text=True, timeout=30,
            env=os.environ.copy(),
        )


class TestCreateHappy(CreateBase):
    def test_writes_yaml_with_all_sections(self):
        r = self._run(_SAMPLE)
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        yp = Path(env["data"]["file_path"])
        self.assertTrue(yp.is_file())
        body = yp.read_text(encoding="utf-8")
        self.assertIn("session: demo", body)
        self.assertIn("goal: test the create subcommand", body)
        self.assertIn("test: python3 -m unittest tests.test_handoff_create", body)
        self.assertIn("- task: wrote tests", body)
        self.assertIn("- implement create", body)
        self.assertIn("status: partial", body)
        self.assertIn("outcome: IN_PROGRESS", body)

    def test_indexes_into_db(self):
        r = self._run(_SAMPLE)
        env = json.loads(r.stdout)
        self.assertIsNotNone(env["data"].get("db_id"))
        self.assertIsInstance(env["data"]["db_id"], int)
        # latest query confirms
        latest = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "latest", "--json"],
            capture_output=True, text=True, timeout=15, env=os.environ.copy(),
        )
        latest_env = json.loads(latest.stdout)
        self.assertEqual(latest_env["data"]["handoff"]["session_id"], "demo")


class TestCreateSchemaValidation(CreateBase):
    def test_missing_required_field_rejected(self):
        bad = dict(_SAMPLE)
        del bad["goal"]
        r = self._run(bad)
        self.assertNotEqual(r.returncode, 0)

    def test_output_validates_against_schema(self):
        import sys as _sys
        _sys.path.insert(0, str(_SCRIPTS))
        import schema_cli
        r = self._run(_SAMPLE)
        env = json.loads(r.stdout)
        m = schema_cli.Manifest.load(_DOMAIN / "handoff.yaml")
        m.get("create").validate_output(env["data"])  # no raise


class TestCreateFilename(CreateBase):
    def test_uses_explicit_slug_and_at(self):
        r = self._run(_SAMPLE)
        env = json.loads(r.stdout)
        self.assertIn("2026-05-17_04-00_test-create.yaml", env["data"]["file_path"])

    def test_derives_slug_from_goal_when_omitted(self):
        payload = dict(_SAMPLE)
        del payload["description_slug"]
        r = self._run(payload)
        env = json.loads(r.stdout)
        # Derived slug should be kebab-form of "test the create subcommand"
        self.assertIn("_test-the-create-subcommand.yaml", env["data"]["file_path"])


class TestCreateNoColonSpaceInProse(CreateBase):
    def test_quotes_value_containing_colon_space(self):
        payload = dict(_SAMPLE)
        payload["goal"] = "fix this: it was broken"  # contains colon-space
        r = self._run(payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        # YAML must still load — use the parser to verify
        import yaml as _yaml
        body = Path(json.loads(r.stdout)["data"]["file_path"]).read_text()
        parts = body.split("---", 2)
        # body (after frontmatter) should parse — no YAML scanner error
        _yaml.safe_load(parts[2])


class TestCreateHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "create", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
