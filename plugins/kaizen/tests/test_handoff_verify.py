"""Tests for handoff.py::verify — lens-driven structural verification.

Replaces the resume Step 3 sub-agent fan-out with a mechanical pass:
walk a handoff YAML's done_this_session.files / worked / failed
sections, run file existence + git log + git grep checks, emit a
typed envelope per schemas/verify-report.schema.json.

The verify subcommand is the canonical exemplar of a lens-wired
subcommand (per schema-driven-cli SKILL.md):
- v2 manifest declares input/output schemas
- domain/verify-rules.yaml drives WHICH checks run
- _cmd_verify walks the rules + emits via lens_emit
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
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
_HANDOFF_PY = _SCRIPTS / "handoff.py"
_DOMAIN = _KZ_DIR / "skills/handoff/domain"

sys.path.insert(0, str(_SCRIPTS))


# ─── A small fixture for handoff YAMLs ───────────────────────────────


def _make_handoff_yaml(
    *,
    date: str = "2026-05-17",
    done_files: list[str] = (),
    worked: list[str] = (),
    failed: list[str] = (),
) -> str:
    """Compose a minimal valid handoff YAML. Hand-built (not via
    textwrap) to keep indentation predictable across embedded list
    items — textwrap.dedent strips common-prefix whitespace, which
    confuses nested-list construction."""
    if done_files:
        done_section = (
            "done_this_session:\n"
            f"  - task: did the thing\n"
            f"    files: [{', '.join(done_files)}]\n"
        )
    else:
        done_section = "done_this_session: []\n"

    if worked:
        worked_section = "worked:\n" + "".join(f"  - {w}\n" for w in worked)
    else:
        worked_section = "worked: []\n"

    if failed:
        failed_section = "failed:\n" + "".join(f"  - {f}\n" for f in failed)
    else:
        failed_section = "failed: []\n"

    return (
        "---\n"
        "session: test-verify\n"
        f"date: {date}\n"
        "status: complete\n"
        "outcome: SUCCEEDED\n"
        "---\n"
        "\n"
        "goal: test fixture\n"
        "now: nothing\n"
        "test: noop\n"
        "\n"
        f"{done_section}"
        "\n"
        "blockers: []\n"
        "questions: []\n"
        "decisions: []\n"
        "findings: []\n"
        f"{worked_section}"
        f"{failed_section}"
        "next: []\n"
        "\n"
        "files:\n"
        "  created: []\n"
        "  modified: []\n"
    )


# ─── Manifest is v2 ─────────────────────────────────────────────────


class TestHandoffManifestV2(unittest.TestCase):
    def test_handoff_manifest_loads_as_v2(self):
        import lens
        manifest_path = _DOMAIN / "handoff.yaml"
        m = lens.Manifest.load(manifest_path)
        self.assertEqual(m.version, 2)
        self.assertEqual(m.feature, "handoff")

    def test_verify_subcommand_declared(self):
        import lens
        m = lens.Manifest.load(_DOMAIN / "handoff.yaml")
        sub = m.get("verify")
        self.assertIsNotNone(sub.output_schema_path)
        self.assertTrue(
            sub.output_schema_path.is_file(),
            f"output schema missing: {sub.output_schema_path}",
        )


# ─── Verify subcommand — subprocess CLI tests ────────────────────────


class HandoffVerifyBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Initialize a git repo for git-based checks
        subprocess.run(
            ["git", "init", "-q", str(self.tmp)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.email", "t@t"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "config", "user.name", "t"],
            check=True, capture_output=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, files: dict[str, str]) -> None:
        for rel, content in files.items():
            p = self.tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.tmp), "add", "."],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tmp), "commit", "-q", "-m", "add"],
            check=True, capture_output=True,
        )

    def _write_handoff(self, yaml_text: str) -> Path:
        p = self.tmp / "handoff.yaml"
        p.write_text(yaml_text, encoding="utf-8")
        return p

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "verify", *args],
            capture_output=True, text=True, timeout=60,
            cwd=str(self.tmp),
        )


class TestVerifyClean(HandoffVerifyBase):
    def test_all_files_present_verdict_clean(self):
        self._commit({"src/lib.py": "def f(): pass\n"})
        yaml_path = self._write_handoff(_make_handoff_yaml(
            done_files=["src/lib.py"],
        ))
        result = self._run("--file", str(yaml_path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["data"]["verdict"], "clean")
        statuses = [c["status"] for c in env["data"]["file_checks"]]
        # Either `present` (no modifications since handoff) or `modified`
        # (touched since handoff date) is acceptable — both are info-severity
        # and roll up to clean. The invariant: no `missing` files.
        self.assertNotIn("missing", statuses)
        self.assertTrue(
            all(s in ("present", "modified") for s in statuses),
            f"unexpected statuses: {statuses}",
        )


class TestVerifyDrift(HandoffVerifyBase):
    def test_missing_file_verdict_drift(self):
        self._commit({"src/keep.py": "x\n"})
        yaml_path = self._write_handoff(_make_handoff_yaml(
            done_files=["src/keep.py", "src/deleted.py"],
        ))
        result = self._run("--file", str(yaml_path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["data"]["verdict"], "drift")
        missing = [c for c in env["data"]["file_checks"] if c["status"] == "missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["path"], "src/deleted.py")


class TestVerifyRegression(HandoffVerifyBase):
    def test_failed_pattern_reintroduced_verdict_regression(self):
        # File contains the failed pattern → regression
        self._commit({"src/oops.py": "def using_deprecated_api(): pass\n"})
        yaml_path = self._write_handoff(_make_handoff_yaml(
            failed=["using_deprecated_api"],
        ))
        result = self._run("--file", str(yaml_path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["data"]["verdict"], "regression")
        bad = [
            c for c in env["data"]["pattern_checks"]
            if c["section"] == "failed" and c["hit_count"] > 0
        ]
        self.assertEqual(len(bad), 1)


class TestVerifyEnvelopeShape(HandoffVerifyBase):
    def test_output_validates_against_schema(self):
        import lens
        self._commit({"x.py": "y\n"})
        yaml_path = self._write_handoff(_make_handoff_yaml(done_files=["x.py"]))
        result = self._run("--file", str(yaml_path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        # Round-trip via lens — re-validate the data payload against
        # the declared schema
        m = lens.Manifest.load(_DOMAIN / "handoff.yaml")
        m.get("verify").validate_output(env["data"])  # no raise

    def test_envelope_has_tool_and_data(self):
        self._commit({"x.py": "y\n"})
        yaml_path = self._write_handoff(_make_handoff_yaml(done_files=["x.py"]))
        result = self._run("--file", str(yaml_path), "--json")
        env = json.loads(result.stdout)
        self.assertEqual(env["kaizen"]["tool"], "kaizen-handoff")
        self.assertIn("data", env)
        # Required fields per the verify-report schema
        for key in ("file_checks", "pattern_checks", "commit_delta", "verdict"):
            self.assertIn(key, env["data"], f"missing {key}")


class TestVerifyCommitDelta(HandoffVerifyBase):
    def test_commit_delta_counts_commits_since_handoff(self):
        self._commit({"a": "1"})
        # Date the handoff well in the past so the next commits land
        # AFTER the handoff date (using YYYY-MM-DD only matters for
        # git's `--since` resolution).
        yaml_path = self._write_handoff(_make_handoff_yaml(
            date="2000-01-01", done_files=["a"],
        ))
        self._commit({"b": "1"})
        self._commit({"c": "1"})
        result = self._run("--file", str(yaml_path), "--json")
        env = json.loads(result.stdout)
        # Expect 2 new commits after the handoff date
        self.assertGreaterEqual(env["data"]["commit_delta"]["count"], 2)


class TestVerifyMissingFileArg(HandoffVerifyBase):
    def test_missing_file_exits_nonzero(self):
        result = self._run("--file", str(self.tmp / "nope.yaml"), "--json")
        self.assertNotEqual(result.returncode, 0)


class TestVerifyHelp(unittest.TestCase):
    def test_help_works(self):
        result = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "verify", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0)


# ─── verify-rules.yaml loads cleanly ─────────────────────────────────


class TestVerifyRulesYaml(unittest.TestCase):
    def test_verify_rules_yaml_exists_and_loads(self):
        import yaml as _yaml
        p = _DOMAIN / "verify-rules.yaml"
        self.assertTrue(p.is_file(), f"verify-rules.yaml missing at {p}")
        data = _yaml.safe_load(p.read_text(encoding="utf-8"))
        self.assertIn("checks", data)
        # Sanity: each check has an id + method
        for chk in data["checks"]:
            self.assertIn("id", chk)
            self.assertIn("method", chk)


if __name__ == "__main__":
    unittest.main()
