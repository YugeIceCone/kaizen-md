"""Tests for handoff.py::get — surgical section extraction.

Per the design exploration this session: a resume agent reading a 14KB
handoff YAML pays ~13K tokens to land ~1.4K of working memory. The `get`
subcommand lets the agent extract one section at a time:

  kaizen-handoff get --file <yaml> --section now
  kaizen-handoff get --file <yaml> --section next --json
  kaizen-handoff get --file <yaml> --section code_context --json

Sections come from:
  Frontmatter: status / outcome / outcome_assigned_by / date / session /
               outcome_justification
  Body:        goal / now / test / done_this_session / blockers /
               questions / decisions / findings / worked / failed /
               next / files / code_context / session_meta

Unknown section → exit code 1 + lists available sections to stderr.
Missing file → exit code 2.
Empty present section → exit code 0 + prints empty string / `[]` / `{}`
depending on shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HANDOFF_PY = _KZ_DIR / "skills/workflow/scripts/handoff.py"


_SAMPLE_HANDOFF = """---
session: demo
date: 2026-05-18
status: complete
outcome: SUCCEEDED
outcome_assigned_by: agent
outcome_justification: "shipped 8 atomic commits, all clean"
---

session_meta:
  cc_session_uuid: "abc-123"
  cc_session_lines: 6500
  handoff_generated_at: "2026-05-18T17:50:00Z"
  primary_branch:
    demo: master
  head_at_handoff:
    demo: deadbeef

goal: did the thing
now: do the next thing
test: pytest -q

done_this_session:
  - task: wrote scaffold
    commits: [sha1, sha2]
    files: [a.py, b.py]
  - task: shipped feature
    commits: [sha3]
    files: [c.py]

blockers: []
questions:
  - Should we wire X now?
decisions:
  - {adopted-X-pattern: rationale}
findings:
  - {key-finding: details}
worked:
  - approach that worked
failed:
  - approach that failed
next:
  - first next step
  - second next step

files:
  demo:
    created: [a.py, b.py]
    modified: [c.py]

code_context:
  - path: a.py
    ranges: ["1:42"]
  - path: b.py
    ranges: ["10:15", "30:45"]
"""


class _GetBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml = self.tmp / "handoff.yaml"
        self.yaml.write_text(_SAMPLE_HANDOFF, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "get", *args],
            capture_output=True, text=True, timeout=15,
        )


class TestGetBodySection(_GetBase):
    def test_get_now_scalar(self):
        r = self._run("--file", str(self.yaml), "--section", "now")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "do the next thing")

    def test_get_goal_scalar(self):
        r = self._run("--file", str(self.yaml), "--section", "goal")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "did the thing")

    def test_get_next_list_default_one_per_line(self):
        r = self._run("--file", str(self.yaml), "--section", "next")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [line for line in r.stdout.strip().splitlines() if line.strip()]
        self.assertEqual(lines, ["first next step", "second next step"])

    def test_get_blockers_empty_list_prints_nothing(self):
        r = self._run("--file", str(self.yaml), "--section", "blockers")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_get_done_this_session_list_of_dicts(self):
        r = self._run("--file", str(self.yaml), "--section",
                       "done_this_session", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["task"], "wrote scaffold")
        self.assertEqual(data[0]["commits"], ["sha1", "sha2"])

    def test_get_code_context_json(self):
        r = self._run("--file", str(self.yaml), "--section",
                       "code_context", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["path"], "a.py")
        self.assertEqual(data[1]["ranges"], ["10:15", "30:45"])


class TestGetFrontmatterSection(_GetBase):
    def test_get_status(self):
        r = self._run("--file", str(self.yaml), "--section", "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "complete")

    def test_get_outcome(self):
        r = self._run("--file", str(self.yaml), "--section", "outcome")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "SUCCEEDED")

    def test_get_date(self):
        r = self._run("--file", str(self.yaml), "--section", "date")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "2026-05-18")


class TestGetSessionMeta(_GetBase):
    def test_get_session_meta_json(self):
        r = self._run("--file", str(self.yaml), "--section",
                       "session_meta", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["cc_session_uuid"], "abc-123")
        self.assertEqual(data["cc_session_lines"], 6500)


class TestGetJsonFlag(_GetBase):
    def test_json_for_scalar(self):
        r = self._run("--file", str(self.yaml), "--section", "now", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout), "do the next thing")

    def test_json_for_list(self):
        r = self._run("--file", str(self.yaml), "--section", "next", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout),
                          ["first next step", "second next step"])


class TestGetUnknownSection(_GetBase):
    def test_unknown_section_exits_1_lists_available(self):
        r = self._run("--file", str(self.yaml), "--section", "banana")
        self.assertEqual(r.returncode, 1)
        # Lists known sections to stderr (helpful for the operator)
        self.assertIn("banana", r.stderr)
        self.assertIn("now", r.stderr)
        self.assertIn("next", r.stderr)


class TestGetMissingFile(_GetBase):
    def test_missing_file_exits_2(self):
        r = self._run("--file", "/nope/missing.yaml", "--section", "now")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not found", r.stderr.lower() + r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
