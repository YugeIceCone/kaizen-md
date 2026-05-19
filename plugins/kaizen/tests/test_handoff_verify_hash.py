"""Tests for handoff.py::verify-hash — finishes the half-built feature.

Scaffold captures `cc_session_sha256` + `cc_session_jsonl` in
session_meta. Until now, `resume` didn't compare against the current
file — silent garbage if the JSONL rotated/truncated/got-overwritten.

`verify-hash --file <handoff.yaml>` re-hashes the linked JSONL and
reports:
  match     — sha matches; resume mining is safe
  drift     — sha mismatch; file mutated since handoff (warn loudly)
  missing   — linked JSONL no longer exists at the captured path
  no-link   — handoff doesn't carry session_meta.cc_session_jsonl
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_HANDOFF_PY = _KZ_DIR / "scripts/handoff/handoff.py"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_yaml(*, jsonl_path: str | None = None,
                  sha: str | None = None) -> str:
    meta = []
    if jsonl_path is not None:
        meta.append(f"  cc_session_jsonl: {jsonl_path!r}")
    if sha is not None:
        meta.append(f"  cc_session_sha256: {sha!r}")
    meta_block = "session_meta:\n" + "\n".join(meta) + "\n" if meta else ""
    return f"""---
session: demo
date: 2026-05-18
status: complete
outcome: SUCCEEDED
---

{meta_block}
goal: x
now: y
"""


class _VerifyHashBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.yaml = self.tmp / "handoff.yaml"
        self.jsonl = self.tmp / "session.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "verify-hash", *args],
            capture_output=True, text=True, timeout=15,
        )


class TestMatch(_VerifyHashBase):
    def test_unchanged_jsonl_reports_match(self):
        content = '{"type": "user", "text": "hello"}\n'
        self.jsonl.write_text(content)
        sha = _sha256(content)
        self.yaml.write_text(_build_yaml(jsonl_path=str(self.jsonl), sha=sha))
        r = self._run("--file", str(self.yaml), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["verdict"], "match")
        self.assertEqual(data["captured_sha"], sha)
        self.assertEqual(data["current_sha"], sha)


class TestDrift(_VerifyHashBase):
    def test_modified_jsonl_reports_drift(self):
        original = '{"type": "user", "text": "hello"}\n'
        sha = _sha256(original)
        self.jsonl.write_text(original)
        self.yaml.write_text(_build_yaml(jsonl_path=str(self.jsonl), sha=sha))
        # Now mutate the file
        self.jsonl.write_text(original + '{"type": "user", "text": "new"}\n')
        r = self._run("--file", str(self.yaml), "--json")
        self.assertNotEqual(r.returncode, 0,
                              "drift should exit non-zero (resume agents must notice)")
        data = json.loads(r.stdout)
        self.assertEqual(data["verdict"], "drift")
        self.assertEqual(data["captured_sha"], sha)
        self.assertNotEqual(data["current_sha"], sha)


class TestMissingJsonl(_VerifyHashBase):
    def test_jsonl_path_no_longer_exists(self):
        # File path captured but file removed
        self.yaml.write_text(_build_yaml(
            jsonl_path=str(self.jsonl), sha="dead" * 16))
        # jsonl never created
        r = self._run("--file", str(self.yaml), "--json")
        self.assertNotEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["verdict"], "missing")


class TestNoLink(_VerifyHashBase):
    def test_handoff_without_session_meta(self):
        self.yaml.write_text(_build_yaml())
        r = self._run("--file", str(self.yaml), "--json")
        # Soft outcome — no fail, but verdict surfaces it
        data = json.loads(r.stdout)
        self.assertEqual(data["verdict"], "no-link")


class TestHumanOutput(_VerifyHashBase):
    def test_default_output_is_human_readable(self):
        self.jsonl.write_text("x\n")
        sha = _sha256("x\n")
        self.yaml.write_text(_build_yaml(jsonl_path=str(self.jsonl), sha=sha))
        r = self._run("--file", str(self.yaml))   # no --json
        self.assertEqual(r.returncode, 0)
        self.assertIn("match", r.stdout.lower())


class TestMissingFile(_VerifyHashBase):
    def test_handoff_file_missing(self):
        r = self._run("--file", "/nope/missing.yaml", "--json")
        # Exit non-zero on missing handoff file
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
