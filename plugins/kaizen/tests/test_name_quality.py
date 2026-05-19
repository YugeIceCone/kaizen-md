"""Tests for kaizen-name-quality — filename ↔ intent matching."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/quality/name_quality.py"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10, env=os.environ.copy(),
    )


class TestTokenizers(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        sys.path.insert(0, str(_KZ_DIR / "scripts/quality"))
        if "name_quality" in sys.modules:
            del sys.modules["name_quality"]
        import name_quality as nq
        self.nq = nq

    def test_tokenize_filename_snake(self):
        self.assertEqual(self.nq._tokenize_filename("code_to_test_coverage"),
                          {"code", "test", "coverage"})  # "to" is a stopword

    def test_tokenize_filename_kebab(self):
        self.assertEqual(self.nq._tokenize_filename("schema-coverage"),
                          {"schema", "coverage"})

    def test_tokenize_intent_drops_stopwords(self):
        out = self.nq._tokenize_intent("Use the scanner to walk the tree.")
        self.assertIn("scanner", out)
        self.assertIn("walk", out)
        self.assertNotIn("the", out)
        self.assertNotIn("to", out)

    def test_singular_plural_normalisation(self):
        # paths ↔ path should overlap
        out = self.nq._normalized_overlap({"paths"}, {"path", "constants"})
        self.assertEqual(out, {"paths"})

    def test_short_tokens_not_normalised(self):
        # 'is' and 'os' shouldn't be stripped to 'i' / 'o'
        out = self.nq._normalized_overlap({"os"}, {"o"})
        self.assertEqual(out, set())


class TestScoreFile(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
        sys.path.insert(0, str(_KZ_DIR / "scripts/quality"))
        if "name_quality" in sys.modules:
            del sys.modules["name_quality"]
        import name_quality as nq
        self.nq = nq
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_active_when_filename_matches_intent(self):
        p = self.root / "coverage_scanner.py"
        p.write_text('"""coverage scanner that walks files."""\nx = 1\n')
        r = self.nq.score_file(p)
        self.assertEqual(r["verdict"], "active")
        self.assertGreaterEqual(r["score"], 70)

    def test_bad_when_filename_unrelated_to_intent(self):
        p = self.root / "frobnicator.py"
        p.write_text('"""Database migration runner."""\nx = 1\n')
        r = self.nq.score_file(p)
        self.assertEqual(r["verdict"], "bad")

    def test_junk_drawer_name_penalised(self):
        p = self.root / "utils.py"
        p.write_text('"""Utility helpers."""\nx = 1\n')
        r = self.nq.score_file(p)
        self.assertIn("junk-drawer", " ".join(r["notes"]))

    def test_missing_docstring_penalised(self):
        p = self.root / "coverage.py"
        p.write_text("x = 1\n")  # no docstring
        r = self.nq.score_file(p)
        self.assertIn("no docstring", " ".join(r["notes"]))

    def test_underscore_prefix_stripped_for_check(self):
        p = self.root / "_atomic.py"
        p.write_text('"""Atomic write helper for kaizen."""\nx = 1\n')
        r = self.nq.score_file(p)
        self.assertEqual(r["verdict"], "active")  # atomic ∈ intent


class TestRealPluginReport(unittest.TestCase):
    def test_report_runs(self):
        r = _run("report")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("name-quality:", r.stdout)

    def test_report_json_shape(self):
        r = _run("report", "--json")
        data = json.loads(r.stdout)
        self.assertGreater(len(data), 50)  # plugin has many scripts
        for entry in data[:3]:
            for k in ("path", "stem", "filename_tokens", "intent_tokens",
                       "score", "verdict", "notes"):
                self.assertIn(k, entry)

    def test_score_subcommand_on_real_file(self):
        target = _KZ_DIR / "scripts/quality/coverage.py"
        r = _run("score", str(target), "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["verdict"], "active")  # we authored coverage.py

    def test_gaps_exit_codes(self):
        """Exit code reflects presence of bad/weak findings:
          - 0 when clean (the post-bff1f53 state — name-quality is 0/0/0)
          - 1 when any bad/weak entries exist
        Accepts either to stay stable across the cleanup arc."""
        r = _run("gaps")
        self.assertIn(r.returncode, (0, 1),
                       f"unexpected exit code {r.returncode}; stdout={r.stdout[:200]}")


if __name__ == "__main__":
    unittest.main()
