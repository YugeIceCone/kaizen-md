#!/usr/bin/env python3
"""Tests for the workflow application layer.

Stdlib unittest; no pytest dep. Run directly:

    python3 _tests.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import _loader  # noqa: E402
import codegen  # noqa: E402


class TestLoader(unittest.TestCase):
    def test_load_routines_returns_dict(self):
        r = _loader.load_routines()
        self.assertIsInstance(r, dict)
        self.assertGreater(len(r), 10)

    def test_load_routines_validates_schema(self):
        # Each routine has required keys
        r = _loader.load_routines()
        for name, entry in r.items():
            for key in ["name", "kind", "stages", "end_state", "description"]:
                self.assertIn(key, entry, f"{name} missing {key}")
            self.assertIn(entry["kind"], ("hardcoded", "schema"))

    def test_load_git_discipline_returns_dict(self):
        g = _loader.load_git_discipline()
        self.assertIn("commit_format", g)
        self.assertIn("sizing_thresholds", g)
        self.assertIn("pre_commit_gates", g)
        self.assertIn("pre_deletion_belief", g)

    def test_get_stages_hardcoded(self):
        # Behavioral parity vs workflow.sh::routine_stages()
        self.assertEqual(
            _loader.get_stages("audit"),
            ["explore", "detect-stack", "research", "audit", "analyze", "review", "create-plan", "create-tasks"],
        )
        self.assertEqual(
            _loader.get_stages("build-feature"),
            ["explore", "detect-stack", "research", "analyze", "create-plan", "create-tasks", "execute-tasks", "simplify", "review", "report"],
        )
        self.assertEqual(
            _loader.get_stages("fix-bug"),
            ["debug", "analyze", "fix", "simplify", "review", "validate", "report"],
        )

    def test_get_stages_unknown_returns_empty(self):
        self.assertEqual(_loader.get_stages("nonexistent-routine"), [])

    def test_detect_routine_matches_verbs(self):
        self.assertEqual(_loader.detect_routine("audit the repo"), "audit")
        self.assertEqual(_loader.detect_routine("fix this bug please"), "fix-bug")
        self.assertEqual(_loader.detect_routine("refactor the parser"), "refactor")
        self.assertEqual(_loader.detect_routine("migrate to typescript 5"), "migrate")
        self.assertEqual(_loader.detect_routine("harden the auth flow"), "harden")
        self.assertEqual(_loader.detect_routine("build a new feature"), "build-feature")
        # Fallback when no verb matches
        self.assertEqual(_loader.detect_routine("xyzzy"), "build-feature")

    def test_detect_routine_handles_empty(self):
        self.assertEqual(_loader.detect_routine(""), "build-feature")
        self.assertEqual(_loader.detect_routine(None), "build-feature")

    def test_verb_matched_explicitly(self):
        self.assertTrue(_loader.verb_matched_explicitly("audit the repo"))
        self.assertTrue(_loader.verb_matched_explicitly("refactor x"))
        self.assertFalse(_loader.verb_matched_explicitly("xyzzy"))
        self.assertFalse(_loader.verb_matched_explicitly(""))


class TestCodegen(unittest.TestCase):
    def test_render_routines_nonempty(self):
        s = codegen._render_routines()
        self.assertIn("# Workflow Routines", s)
        self.assertIn("audit", s)
        self.assertIn("build-feature", s)
        # Generated header present
        self.assertIn("DO NOT HAND-EDIT", s)

    def test_render_git_discipline_nonempty(self):
        s = codegen._render_git_discipline()
        self.assertIn("# Git Workflow Discipline", s)
        self.assertIn("Pre-commit gates", s)
        self.assertIn("DO NOT HAND-EDIT", s)

    def test_codegen_idempotent(self):
        """Running twice in a row produces byte-identical output."""
        first = codegen._render_routines()
        second = codegen._render_routines()
        self.assertEqual(first, second, "routines.md generation is non-deterministic")

        first_gd = codegen._render_git_discipline()
        second_gd = codegen._render_git_discipline()
        self.assertEqual(first_gd, second_gd, "git-discipline.md generation is non-deterministic")

    def test_write_atomic_no_change(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.md"
            content = "hello\n"
            self.assertTrue(codegen._write_atomic(p, content))   # first write
            self.assertFalse(codegen._write_atomic(p, content))  # no-op second write
            self.assertTrue(codegen._write_atomic(p, content + "x"))  # diff content writes


class TestCLI(unittest.TestCase):
    def _run(self, *args, expect_rc: int = 0) -> tuple[int, str, str]:
        import subprocess
        r = subprocess.run(
            ["python3", str(SCRIPT_DIR / "_loader.py")] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode, r.stdout, r.stderr

    def test_cli_list(self):
        rc, out, _ = self._run("list")
        self.assertEqual(rc, 0)
        names = out.strip().split("\n")
        self.assertIn("audit", names)
        self.assertIn("build-feature", names)
        self.assertIn("fix-bug", names)

    def test_cli_stages(self):
        rc, out, _ = self._run("stages", "audit")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "explore detect-stack research audit analyze review create-plan create-tasks")

    def test_cli_stages_unknown(self):
        rc, _, _ = self._run("stages", "nonexistent-xyz")
        self.assertNotEqual(rc, 0)

    def test_cli_validate(self):
        rc, out, _ = self._run("validate")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "ok")

    def test_cli_detect(self):
        rc, out, _ = self._run("detect", "audit the repo")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "audit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
