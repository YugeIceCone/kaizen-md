"""Tests for handoff.py::assess — deterministic outcome rubric.

The `assess` subcommand computes mechanical signals from a handoff
YAML, walks the BucketWalker rubric at
`skills/handoff/domain/outcome-rubric.yaml`, and returns a typed
recommendation envelope. When the rubric falls through (no rule
matches), it returns `NEEDS_AGENT` so the calling agent picks
qualitatively.

The agent then passes the recommended bucket to `auto-finalize
--outcome <X>` to finalize the YAML — `assess` is read-only.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "scripts/handoff"
_HANDOFF_PY = _SCRIPTS / "handoff.py"
_DOMAIN = _KZ_DIR / "skills/handoff/domain"
_RUBRIC = _DOMAIN / "outcome-rubric.yaml"

sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_KZ_DIR / "scripts/rules"))


def _yaml_with(
    *,
    done: list[str] = (),
    blockers: list[str] = (),
    next_items: list[str] = (),
    date: str = "2026-05-17",
) -> str:
    """Compose a minimal handoff YAML with the sections that drive
    rubric signals. Hand-built (no textwrap) for indent predictability."""
    done_section = (
        "done_this_session:\n"
        + "".join(
            f"  - task: {t}\n    files: []\n"
            for t in done
        ) if done else "done_this_session: []\n"
    )
    blockers_section = (
        "blockers:\n" + "".join(f"  - {b}\n" for b in blockers)
        if blockers else "blockers: []\n"
    )
    next_section = (
        "next:\n" + "".join(f"  - {n}\n" for n in next_items)
        if next_items else "next: []\n"
    )
    return (
        "---\n"
        f"session: test-assess\n"
        f"date: {date}\n"
        "status: partial\n"
        "outcome: IN_PROGRESS\n"
        "---\n\n"
        "goal: test\nnow: test\ntest: noop\n\n"
        f"{done_section}\n"
        f"{blockers_section}"
        "questions: []\n"
        "decisions: []\n"
        "findings: []\n"
        "worked: []\n"
        "failed: []\n"
        f"{next_section}\n"
        "files:\n  created: []\n  modified: []\n"
    )


# ─── Rubric yaml exists + loads via BucketWalker ─────────────────────


class TestRubricLoads(unittest.TestCase):
    def test_rubric_yaml_exists(self):
        self.assertTrue(_RUBRIC.is_file(),
                        f"outcome-rubric.yaml missing at {_RUBRIC}")

    def test_walker_loads_rubric(self):
        import schema_cli as lens
        w = lens.BucketWalker.from_yaml(_RUBRIC)
        # Sanity: each of the four canonical buckets has at least one rule
        buckets = {r.bucket for r in w.rules}
        self.assertIn("SUCCEEDED",     buckets)
        self.assertIn("PARTIAL_PLUS",  buckets)
        self.assertIn("PARTIAL_MINUS", buckets)
        self.assertIn("FAILED",        buckets)


# ─── assess CLI ──────────────────────────────────────────────────────


class HandoffAssessBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, content: str) -> Path:
        p = self.tmp / "handoff.yaml"
        p.write_text(content, encoding="utf-8")
        return p

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "assess", *args],
            capture_output=True, text=True, timeout=30,
        )


class TestAssessSucceeded(HandoffAssessBase):
    def test_all_done_no_blockers_no_next_blocking_picks_succeeded(self):
        p = self._write(_yaml_with(done=["wrote tests", "shipped feature"]))
        r = self._run("--file", str(p), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "SUCCEEDED")
        self.assertEqual(env["data"]["method"], "deterministic")


class TestAssessPartialMinus(HandoffAssessBase):
    def test_blocker_present_picks_partial_minus(self):
        p = self._write(_yaml_with(
            done=["one task"],
            blockers=["external dep broken"],
        ))
        r = self._run("--file", str(p), "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "PARTIAL_MINUS")


class TestAssessFailed(HandoffAssessBase):
    def test_test_delta_negative_picks_failed(self):
        p = self._write(_yaml_with(done=["x"]))
        r = self._run("--file", str(p), "--test-delta", "-3", "--json")
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "FAILED")


class TestAssessNextBlocking(HandoffAssessBase):
    def test_next_blocking_keyword_blocks_succeeded(self):
        # All done, no blockers, but a `next:` item flagged as blocking
        # → doesn't qualify for SUCCEEDED (which requires
        # next_blocking_count == 0)
        p = self._write(_yaml_with(
            done=["x"],
            next_items=["must-fix the auth regression before merge"],
        ))
        r = self._run("--file", str(p), "--json")
        env = json.loads(r.stdout)
        self.assertNotEqual(env["data"]["bucket"], "SUCCEEDED")


class TestAssessSignalsInOutput(HandoffAssessBase):
    def test_signals_payload_includes_computed_values(self):
        p = self._write(_yaml_with(
            done=["a", "b"],
            blockers=["x"],
            next_items=["nothing scary"],
        ))
        r = self._run("--file", str(p), "--json")
        env = json.loads(r.stdout)
        sig = env["data"]["signals"]
        self.assertEqual(sig["done_count"], 2)
        self.assertEqual(sig["blocker_count"], 1)
        # next item without blocking-keyword → next_blocking_count=0
        self.assertEqual(sig["next_blocking_count"], 0)
        self.assertIn("completed_ratio", sig)


class TestAssessRationaleIncluded(HandoffAssessBase):
    def test_rationale_in_envelope(self):
        p = self._write(_yaml_with(done=["x"]))
        r = self._run("--file", str(p), "--json")
        env = json.loads(r.stdout)
        self.assertIn("rationale", env["data"])
        self.assertTrue(env["data"]["rationale"])  # non-empty


class TestAssessOutputSchemaValid(HandoffAssessBase):
    def test_envelope_data_validates(self):
        import schema_cli as lens
        p = self._write(_yaml_with(done=["x"]))
        r = self._run("--file", str(p), "--json")
        env = json.loads(r.stdout)
        m = lens.Manifest.load(_DOMAIN / "handoff.yaml")
        m.get("assess").validate_output(env["data"])  # no raise


class TestAssessFileNotFound(HandoffAssessBase):
    def test_missing_file_exits_nonzero(self):
        r = self._run("--file", str(self.tmp / "nope.yaml"), "--json")
        self.assertNotEqual(r.returncode, 0)


# ─── Parse-error resilience — silent FAILED guard (regression cover) ─


_BROKEN_YAML = """---
session: x
date: 2026-05-19
status: partial
outcome: IN_PROGRESS
---

goal: x
now: x
test: noop

done_this_session:
  - task: real work that landed
    files: []
failed:
  - 'Slash bodies need `!`bash -c 'exec ${BIN}'`` not `!`bash ${BIN}``.'
blockers: []
next: []
questions: []
decisions: []
findings: []
worked: []
"""


class TestAssessParseError(HandoffAssessBase):
    """A YAML parse failure must NOT silently produce FAILED via
    empty-signals. It must surface as bucket=NEEDS_AGENT,
    method=parse_error, with a clear rationale — so the agent knows
    the YAML is malformed, not the work."""

    def test_broken_yaml_returns_needs_agent_not_failed(self):
        p = self._write(_BROKEN_YAML)
        r = self._run("--file", str(p), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(env["data"]["bucket"], "NEEDS_AGENT",
                         f"silent FAILED on parse error: {env['data']}")
        self.assertEqual(env["data"]["method"], "parse_error")
        self.assertIn("parse", env["data"]["rationale"].lower())


class TestParserSurfacesError(unittest.TestCase):
    """Unit-level: _parse_handoff_yaml must record the failure, not
    silently return an empty body."""

    def test_parse_error_field_present_on_failure(self):
        from handoff import _parse_handoff_yaml
        parsed = _parse_handoff_yaml(_BROKEN_YAML)
        self.assertIn("_parse_error", parsed)
        self.assertTrue(parsed["_parse_error"])

    def test_parse_error_absent_on_clean_yaml(self):
        from handoff import _parse_handoff_yaml
        parsed = _parse_handoff_yaml(_yaml_with(done=["x"]))
        self.assertNotIn("_parse_error", parsed)


class TestAssessHelp(unittest.TestCase):
    def test_help_works(self):
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "assess", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0)


# ─── Signal computer unit tests (pure-Python, no subprocess) ─────────


class TestSignalsComputer(unittest.TestCase):
    """Direct unit tests on _compute_assessment_signals."""

    def test_done_count_from_done_this_session(self):
        from handoff import _compute_assessment_signals
        parsed = {"done_count_raw": 0, "done_items": [{"task": "a"}, {"task": "b"}],
                  "blockers": [], "next": [], "questions": [],
                  "test_delta": 0}
        sig = _compute_assessment_signals(parsed)
        self.assertEqual(sig["done_count"], 2)

    def test_completed_ratio_with_blockers_and_next(self):
        from handoff import _compute_assessment_signals
        parsed = {
            "done_items": [{"task": "a"}, {"task": "b"}],
            "blockers": ["x"], "next": ["y", "z"],
            "questions": [], "test_delta": 0,
        }
        sig = _compute_assessment_signals(parsed)
        # ratio = done / (done + blockers + next) = 2 / (2 + 1 + 2) = 0.4
        self.assertAlmostEqual(sig["completed_ratio"], 0.4, places=2)

    def test_next_blocking_count_detects_keywords(self):
        from handoff import _compute_assessment_signals
        parsed = {
            "done_items": [],
            "blockers": [],
            "next": [
                "do the thing",                       # not blocking
                "must-fix the auth regression",       # blocking
                "critical: ship before merge",        # blocking
                "blocking — needs review",            # blocking
                "TODO: nothing scary",                # blocking (TODO keyword)
            ],
            "questions": [], "test_delta": 0,
        }
        sig = _compute_assessment_signals(parsed)
        self.assertEqual(sig["next_blocking_count"], 4)

    def test_empty_handoff_completed_ratio_is_zero(self):
        from handoff import _compute_assessment_signals
        parsed = {"done_items": [], "blockers": [], "next": [],
                  "questions": [], "test_delta": 0}
        sig = _compute_assessment_signals(parsed)
        self.assertEqual(sig["completed_ratio"], 0)


if __name__ == "__main__":
    unittest.main()
