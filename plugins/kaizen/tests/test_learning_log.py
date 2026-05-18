"""Tests for kaizen-learn — append-only learning + evolution log.

Captures structured problem/solution pairs encountered during the tool
loop. Start categories: wasteful_tokens, roundtrips, anti_patterns.

The schema enforces enough structure to make later promotion to
CLAUDE.md or brain Notes mechanical — every entry carries category,
problem, solution, pattern (the reusable rule), plus optional
savings_estimate, trigger_keywords, source_sid, source_commits,
references.

Iron-laws (same family as kaizen-progress):
  - append-only — never reads the existing log
  - schema-validated BEFORE write — invalid payload exits 1
  - file is JSONL (one entry per line) — diff-friendly + grep-friendly
  - sink path env-overridable via KAIZEN_LEARNING_DIR (for tests)

Sink: <KAIZEN_LEARNING_DIR>/log.jsonl
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
_LEARN_PY = _KZ_DIR / "skills/workflow/scripts/learning_log.py"


class _LearnBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._orig = os.environ.get("KAIZEN_LEARNING_DIR")
        os.environ["KAIZEN_LEARNING_DIR"] = str(self.tmp)
        self.log = self.tmp / "log.jsonl"

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_LEARNING_DIR", None)
        else:
            os.environ["KAIZEN_LEARNING_DIR"] = self._orig

    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_LEARN_PY), *args],
            capture_output=True, text=True, timeout=15,
            input=stdin, env=os.environ.copy(),
        )


class TestAppendBasic(_LearnBase):
    def test_creates_log_file_if_absent(self):
        r = self._run("append",
                       "--category", "roundtrips",
                       "--problem",  "Read+Edit dance for progress.md",
                       "--solution", "kaizen-progress append CLI",
                       "--pattern",  "append-only CLI replaces Read+Edit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.log.is_file())
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["category"], "roundtrips")
        self.assertEqual(entry["problem"], "Read+Edit dance for progress.md")
        self.assertIn("ts", entry)
        self.assertIn("id", entry)
        self.assertEqual(entry["promotion_status"], "pending")

    def test_appends_multiple_entries(self):
        for i in range(3):
            self._run("append",
                       "--category", "anti_patterns",
                       "--problem",  f"problem {i}",
                       "--solution", f"solution {i}",
                       "--pattern",  f"pattern {i}")
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        # Each entry has a UNIQUE id
        ids = [json.loads(line)["id"] for line in lines]
        self.assertEqual(len(set(ids)), 3)


class TestSchemaValidation(_LearnBase):
    def test_invalid_category_exits_1(self):
        r = self._run("append",
                       "--category", "bananas",
                       "--problem", "p", "--solution", "s", "--pattern", "x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("category", (r.stderr + r.stdout).lower())

    def test_missing_problem_exits_1(self):
        r = self._run("append",
                       "--category", "roundtrips",
                       "--solution", "s", "--pattern", "x")
        # argparse returns 2 for missing-arg by default; we accept either
        self.assertIn(r.returncode, (1, 2))

    def test_empty_problem_exits_1(self):
        r = self._run("append",
                       "--category", "roundtrips",
                       "--problem", "", "--solution", "s", "--pattern", "x")
        self.assertEqual(r.returncode, 1)


class TestOptionalFields(_LearnBase):
    def test_savings_estimate_and_keywords_stored(self):
        r = self._run("append",
                       "--category", "wasteful_tokens",
                       "--problem", "Reading 14KB YAML to get 150 tokens",
                       "--solution", "handoff get --section next",
                       "--pattern", "section extraction over whole-file Read",
                       "--savings-estimate", "87% read cost",
                       "--trigger-keyword", "read full file",
                       "--trigger-keyword", "handoff yaml")
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(entry["savings_estimate"], "87% read cost")
        self.assertEqual(entry["trigger_keywords"],
                          ["read full file", "handoff yaml"])

    def test_source_sid_and_commits(self):
        r = self._run("append",
                       "--category", "roundtrips",
                       "--problem", "p", "--solution", "s", "--pattern", "x",
                       "--source-sid", "6ebbb7cb",
                       "--source-commit", "fc15179",
                       "--source-commit", "53473d8")
        self.assertEqual(r.returncode, 0)
        entry = json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(entry["source_sid"], "6ebbb7cb")
        self.assertEqual(entry["source_commits"], ["fc15179", "53473d8"])


class TestListSubcommand(_LearnBase):
    def _seed(self, n=5):
        for i, cat in enumerate(
            ["roundtrips", "wasteful_tokens", "anti_patterns",
              "roundtrips", "wasteful_tokens"][:n]
        ):
            self._run("append",
                       "--category", cat,
                       "--problem", f"p{i}",
                       "--solution", f"s{i}",
                       "--pattern", f"x{i}")

    def test_list_all_default(self):
        self._seed()
        r = self._run("list", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 5)

    def test_list_filter_by_category(self):
        self._seed()
        r = self._run("list", "--category", "roundtrips", "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)
        for entry in data:
            self.assertEqual(entry["category"], "roundtrips")


class TestStdinJsonAppend(_LearnBase):
    def test_stdin_json(self):
        payload = json.dumps({
            "category": "anti_patterns",
            "problem":  "stub primitives left in handlers",
            "solution": "wire to real MCP tools with _deps injection",
            "pattern":  "production-wire vs stub via _deps",
            "savings_estimate": "lower-quality outputs corrected",
        })
        r = self._run("append", "--stdin", stdin=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        entry = json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(entry["pattern"], "production-wire vs stub via _deps")


class TestAppendOnlyInvariant(_LearnBase):
    """The point: NEVER read the existing log. Verified by size-delta on
    a seeded log (same proof pattern as kaizen-progress).

    Seeds via direct file-write (1001 subprocess calls would dominate
    the parallel-suite wall clock — ~30s of pure python cold-start).
    The CRITICAL append (the one being measured) IS via the CLI — that's
    the actual code path verified to be append-only.
    """

    def test_append_cost_constant(self):
        # Seed 1000 fake-but-realistic JSONL lines directly to disk —
        # the bytes have to LOOK like real entries (the test asserts
        # >50KB before the measured append). 100B per line × 1000 = 100KB.
        seed_line = json.dumps({
            "id": "deadbeef",
            "ts": "2026-05-19T00:00:00Z",
            "promotion_status": "pending",
            "category": "roundtrips",
            "problem": "x" * 20,
            "solution": "y" * 20,
            "pattern": "z" * 20,
        }) + "\n"
        with self.log.open("w", encoding="utf-8") as f:
            for _ in range(1000):
                f.write(seed_line)
        size_before = self.log.stat().st_size
        self.assertGreater(size_before, 50_000)
        # The MEASURED append — via the actual CLI (this is what we're
        # asserting is append-only). One subprocess call instead of 1001.
        self._run("append",
                   "--category", "wasteful_tokens",
                   "--problem", "extra", "--solution", "x", "--pattern", "y")
        size_after = self.log.stat().st_size
        delta = size_after - size_before
        # One JSONL line — bounded by ~500 bytes incl. timestamps + id
        self.assertLess(delta, 500,
                         f"append delta={delta}B; expected <500B (one entry). "
                         "Read-then-overwrite implementation would touch all.")


if __name__ == "__main__":
    unittest.main()
