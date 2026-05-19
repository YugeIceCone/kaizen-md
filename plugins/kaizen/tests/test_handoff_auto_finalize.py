"""Tests for handoff.py::auto-finalize — agent-assigned outcome flow.

The auto-finalize subcommand encapsulates Step 4 of the handoff `create`
skill flow when Claude (or any agent) self-assesses the outcome instead
of asking the user via AskUserQuestion. Mandatory for subagent contexts
(no AskUserQuestion available) and the default behavior in interactive
sessions (per user spec).

Behavior:
- Reads a handoff YAML at --file
- Rewrites the frontmatter `status:` and `outcome:` to the supplied values
- Optionally writes `outcome_justification:` and `outcome_assigned_by:`
  audit fields (latter defaults to "agent")
- Re-indexes the YAML into the SQLite store
- Atomic write (tempfile + rename), preserves non-frontmatter body verbatim
- Idempotent — re-running with the same values is a no-op semantically
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
_SCRIPTS = _KZ_DIR / "scripts/handoff"
_HANDOFF = _SCRIPTS / "handoff.py"


_PLACEHOLDER_YAML = textwrap.dedent("""\
    ---
    session: test-session
    date: 2026-05-17
    status: partial
    outcome: IN_PROGRESS
    ---

    goal: test the auto-finalize subcommand end-to-end.
    now: assert outcome + status + audit fields land in frontmatter.
    test: python3 -m unittest tests.test_handoff_auto_finalize

    done_this_session:
      - task: wrote tests
        files: [tests/test_handoff_auto_finalize.py]

    blockers: []
    questions: []
    decisions: []
    findings: []
    worked: []
    failed: []

    next:
      - implement auto-finalize subcommand

    files:
      created: []
      modified: []
""")


class HandoffAutoFinalizeBase(unittest.TestCase):
    """Sandboxes the handoff DB + YAML dir per-test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml_dir = self.tmp / "handoffs" / "test-session"
        self.yaml_dir.mkdir(parents=True)
        self.yaml_path = self.yaml_dir / "2026-05-17_00-00_test.yaml"
        self.yaml_path.write_text(_PLACEHOLDER_YAML, encoding="utf-8")

        self.db_path = self.tmp / "handoff.db"
        self._orig_db = os.environ.get("KAIZEN_HANDOFF_DB")
        self._orig_dir = os.environ.get("KAIZEN_HANDOFF_DIR")
        os.environ["KAIZEN_HANDOFF_DB"] = str(self.db_path)
        os.environ["KAIZEN_HANDOFF_DIR"] = str(self.tmp / "handoffs")

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (
            ("KAIZEN_HANDOFF_DB", self._orig_db),
            ("KAIZEN_HANDOFF_DIR", self._orig_dir),
        ):
            if orig is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = orig

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy(),
        )

    def _read_frontmatter(self) -> dict:
        """Parse the YAML frontmatter as a flat key→value dict (line-based)."""
        text = self.yaml_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        fm = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip()
        return fm


class TestSubcommandWired(HandoffAutoFinalizeBase):
    def test_auto_finalize_help_works(self):
        result = self._run("auto-finalize", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("auto-finalize", result.stdout.lower())

    def test_missing_file_arg_errors(self):
        result = self._run("auto-finalize", "--outcome", "SUCCEEDED")
        self.assertNotEqual(result.returncode, 0)


class TestFrontmatterRewrite(HandoffAutoFinalizeBase):
    def test_outcome_succeeded_is_written_to_frontmatter(self):
        result = self._run(
            "auto-finalize",
            "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        fm = self._read_frontmatter()
        self.assertEqual(fm.get("outcome"), "SUCCEEDED")

    def test_status_defaults_to_complete(self):
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        fm = self._read_frontmatter()
        self.assertEqual(fm.get("status"), "complete")

    def test_explicit_status_partial_is_written(self):
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "PARTIAL_PLUS", "--status", "partial",
        )
        fm = self._read_frontmatter()
        self.assertEqual(fm.get("status"), "partial")
        self.assertEqual(fm.get("outcome"), "PARTIAL_PLUS")

    def test_body_preserved_verbatim(self):
        """The non-frontmatter body must survive unchanged."""
        before = self.yaml_path.read_text(encoding="utf-8")
        before_body = before.split("---", 2)[2]
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        after = self.yaml_path.read_text(encoding="utf-8")
        after_body = after.split("---", 2)[2]
        self.assertEqual(before_body, after_body)

    def test_outcome_assigned_by_defaults_to_agent(self):
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        fm = self._read_frontmatter()
        self.assertEqual(fm.get("outcome_assigned_by"), "agent")

    def test_outcome_assigned_by_can_be_user(self):
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED", "--assigned-by", "user",
        )
        fm = self._read_frontmatter()
        self.assertEqual(fm.get("outcome_assigned_by"), "user")

    def test_justification_is_written_when_provided(self):
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "PARTIAL_PLUS",
            "--justification",
            "all done_this_session tasks landed; 1 question open",
        )
        fm = self._read_frontmatter()
        # justification text contains spaces but no colon — line-based
        # parser should capture it as a single value.
        self.assertIn("done_this_session", fm.get("outcome_justification", ""))

    def test_idempotent_rerun(self):
        """Re-running with same args should leave the YAML in the same shape."""
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        once = self.yaml_path.read_text(encoding="utf-8")
        self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        twice = self.yaml_path.read_text(encoding="utf-8")
        self.assertEqual(once, twice)


class TestStoreIndexing(HandoffAutoFinalizeBase):
    def test_db_row_carries_final_status(self):
        # First save with placeholder status
        save = self._run(
            "save", "--session", "test-session",
            "--file", str(self.yaml_path), "--status", "partial",
        )
        self.assertEqual(save.returncode, 0, save.stderr)

        # Auto-finalize → status should flip to complete
        result = self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # Latest query reads from DB; should show complete + SUCCEEDED content
        latest = self._run("latest", "--json")
        env = json.loads(latest.stdout)
        h = env["data"]["handoff"]
        self.assertEqual(h["status"], "complete")
        self.assertIn("SUCCEEDED", h["content"])


class TestJsonEnvelope(HandoffAutoFinalizeBase):
    def test_json_output_is_envelope_shaped(self):
        result = self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        # Canonical envelope: kaizen meta block + data payload
        self.assertIn("kaizen", env)
        self.assertEqual(env["kaizen"]["tool"], "kaizen-handoff")
        self.assertIn("data", env)
        self.assertEqual(env["data"]["outcome"], "SUCCEEDED")
        self.assertEqual(env["data"]["status"], "complete")


class TestOutcomeValidation(HandoffAutoFinalizeBase):
    def test_invalid_outcome_rejected(self):
        result = self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "NOT_A_REAL_OUTCOME",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_status_rejected(self):
        result = self._run(
            "auto-finalize", "--file", str(self.yaml_path),
            "--outcome", "SUCCEEDED", "--status", "not-a-status",
        )
        self.assertNotEqual(result.returncode, 0)


class TestMissingFile(HandoffAutoFinalizeBase):
    def test_missing_yaml_file_exits_non_zero(self):
        result = self._run(
            "auto-finalize",
            "--file", str(self.tmp / "does-not-exist.yaml"),
            "--outcome", "SUCCEEDED",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr.lower() + result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
