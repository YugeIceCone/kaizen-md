"""Tests for the kaizen-rubric CLI — rubric prototyping helper.

Exposes the BucketWalker pattern as a standalone CLI so an agent
can iterate on a rubric YAML without writing a feature CLI first.
Pairs with the `decision-rubric` skill (SKILL.md).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_RUBRIC_PY = _KZ_DIR / "scripts" / "rules" / "rubric.py"


class RubricCliBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_rubric(self, content: str) -> Path:
        p = self.tmp / "rubric.yaml"
        p.write_text(content, encoding="utf-8")
        return p

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_RUBRIC_PY), *args],
            capture_output=True, text=True, timeout=30,
        )


class TestRubricEval(RubricCliBase):
    def test_clean_match_picks_bucket(self):
        rp = self._write_rubric(textwrap.dedent("""\
            rules:
              - bucket: GREEN
                require_all:
                  - {signal: x, op: ">=", value: 5}
              - bucket: RED
                require_any:
                  - {signal: x, op: "<", value: 5}
            confidence_threshold: 0.85
            fallback: NEEDS_AGENT
        """))
        r = self._run(
            "eval", "--rubric", str(rp), "--signals", '{"x": 7}', "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "GREEN")
        self.assertEqual(env["data"]["method"], "deterministic")

    def test_no_match_falls_back(self):
        rp = self._write_rubric(textwrap.dedent("""\
            rules:
              - bucket: NARROW
                require_all:
                  - {signal: x, op: "==", value: 999}
            fallback: NEEDS_AGENT
        """))
        r = self._run("eval", "--rubric", str(rp), "--signals", '{"x": 1}', "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "NEEDS_AGENT")
        self.assertEqual(env["data"]["method"], "fallback")

    def test_signals_from_file(self):
        rp = self._write_rubric(textwrap.dedent("""\
            rules:
              - bucket: HIT
                require_all:
                  - {signal: n, op: ">", value: 0}
            fallback: NEEDS_AGENT
        """))
        sig_path = self.tmp / "sig.json"
        sig_path.write_text('{"n": 5}', encoding="utf-8")
        r = self._run(
            "eval", "--rubric", str(rp),
            "--signals-file", str(sig_path), "--json",
        )
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "HIT")

    def test_invalid_signals_json_errors(self):
        rp = self._write_rubric(
            "rules:\n  - bucket: X\n    require_all: []\nfallback: NEEDS_AGENT\n"
        )
        r = self._run(
            "eval", "--rubric", str(rp), "--signals", "not-json", "--json",
        )
        self.assertNotEqual(r.returncode, 0)

    def test_missing_rubric_errors(self):
        r = self._run(
            "eval", "--rubric", str(self.tmp / "nope.yaml"),
            "--signals", "{}", "--json",
        )
        self.assertNotEqual(r.returncode, 0)


class TestRubricEnvelope(RubricCliBase):
    def test_envelope_has_canonical_meta(self):
        rp = self._write_rubric(textwrap.dedent("""\
            rules:
              - bucket: OK
                require_all:
                  - {signal: x, op: "==", value: 1}
            fallback: NEEDS_AGENT
        """))
        r = self._run("eval", "--rubric", str(rp), "--signals", '{"x":1}', "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["kaizen"]["tool"], "kaizen-rubric")
        self.assertIn("data", env)
        for key in ("bucket", "method", "confidence", "rationale", "signals"):
            self.assertIn(key, env["data"], f"missing {key}")


class TestRubricLint(RubricCliBase):
    """`lint` validates a rubric yaml's structural shape."""

    def test_valid_rubric_passes(self):
        rp = self._write_rubric(textwrap.dedent("""\
            rules:
              - bucket: A
                require_all:
                  - {signal: x, op: ">=", value: 0}
            fallback: NEEDS_AGENT
        """))
        r = self._run("lint", "--rubric", str(rp), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["verdict"], "clean")

    def test_unknown_op_rejected(self):
        rp = self._write_rubric(textwrap.dedent("""\
            rules:
              - bucket: A
                require_all:
                  - {signal: x, op: "approximately", value: 0}
            fallback: NEEDS_AGENT
        """))
        r = self._run("lint", "--rubric", str(rp), "--json")
        self.assertNotEqual(r.returncode, 0)


class TestRubricHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run(
            [sys.executable, str(_RUBRIC_PY), "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
