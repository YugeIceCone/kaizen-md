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
import route_intent  # noqa: E402


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

    def test_get_stages_unknown_returns_defaults(self):
        # Phase B (2026-05-13): unknown names now resolve to defaults.stages
        # from routines.yaml (was `[]` pre-merge). See TestRoutingDefaults below.
        defaults = _loader.load_defaults()
        self.assertEqual(_loader.get_stages("nonexistent-routine"), defaults["stages"])

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

    def test_cli_stages_unknown_returns_defaults(self):
        # Phase B (2026-05-13): unknown names return defaults.stages and
        # exit 0 (was non-zero pre-merge).
        rc, out, _ = self._run("stages", "nonexistent-xyz")
        self.assertEqual(rc, 0)
        defaults = _loader.load_defaults()
        self.assertEqual(out.strip(), " ".join(defaults["stages"]))

    def test_cli_validate(self):
        rc, out, _ = self._run("validate")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "ok")

    def test_cli_detect(self):
        rc, out, _ = self._run("detect", "audit the repo")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "audit")


class TestRoutingDefaults(unittest.TestCase):
    def test_load_defaults_returns_required_keys(self):
        d = _loader.load_defaults()
        self.assertIn("routine", d)
        self.assertIn("stages", d)
        self.assertIsInstance(d["stages"], list)
        self.assertGreater(len(d["stages"]), 0)

    def test_defaults_routine_is_real(self):
        d = _loader.load_defaults()
        routines = _loader.load_routines()
        self.assertIn(d["routine"], routines,
                      "defaults.routine must reference a real routine in routines.yaml")

    def test_get_stages_unknown_uses_defaults(self):
        # Phase B: unknown routine names now resolve to defaults.stages
        # instead of returning empty (which the bash wrapper used to backfill).
        d = _loader.load_defaults()
        self.assertEqual(_loader.get_stages("nonexistent-routine-xyz"), d["stages"])

    def test_get_stages_custom_stays_empty(self):
        # `custom` is the documented opt-out for user-pinned-skill workflows.
        self.assertEqual(_loader.get_stages("custom"), [])

    def test_detect_routine_no_match_uses_defaults(self):
        d = _loader.load_defaults()
        self.assertEqual(_loader.detect_routine("xyzzy nonsense prompt"), d["routine"])


class TestStageSkillMap(unittest.TestCase):
    """Phase C — stage_skill_map block in routines.yaml."""

    def test_loads_as_dict(self):
        m = _loader.load_stage_skill_map()
        self.assertIsInstance(m, dict)
        self.assertGreaterEqual(len(m), 15, "expected at least the 15 workflow-stage skills")

    def test_workflow_stages_have_skills(self):
        m = _loader.load_stage_skill_map()
        for stage in ["analyze", "audit", "create-plan", "create-tasks", "debug",
                      "execute-plan", "execute-tasks", "fix", "migrate", "refactor",
                      "report", "review", "supervisor", "task", "validate"]:
            self.assertIn(stage, m, f"missing stage->skill: {stage}")

    def test_get_skill_for_known_stage(self):
        self.assertEqual(_loader.get_skill_for_stage("analyze"), "kaizen:analyze")
        self.assertEqual(_loader.get_skill_for_stage("audit"), "kaizen:audit")

    def test_get_skill_for_unmapped_stage_returns_none(self):
        # `simplify` is intentionally a slash command, not a skill.
        self.assertIsNone(_loader.get_skill_for_stage("simplify"))
        self.assertIsNone(_loader.get_skill_for_stage("nonexistent-stage-xyz"))

    def test_every_mapped_skill_exists_in_plugin_tree(self):
        """Every kaizen:<skill> mapping must point at a real skill dir
        with a SKILL.md. Catches drift if a skill is renamed/deleted."""
        plugin_skills_dir = SCRIPT_DIR.parent.parent
        m = _loader.load_stage_skill_map()
        for stage, full_skill in m.items():
            if not full_skill.startswith("kaizen:"):
                continue
            leaf = full_skill.split(":", 1)[1]
            skill_md = plugin_skills_dir / leaf / "SKILL.md"
            self.assertTrue(
                skill_md.is_file(),
                f"stage_skill_map: {stage} -> {full_skill} but {skill_md} missing",
            )


class TestIntentRouting(unittest.TestCase):
    def test_load_validates_and_returns_dict(self):
        cfg = route_intent.load()
        self.assertIn("routes", cfg)
        self.assertGreaterEqual(len(cfg["routes"]), 9)

    def test_every_route_has_unique_id(self):
        cfg = route_intent.load()
        ids = [r["id"] for r in cfg["routes"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_disambiguation_pairs_resolve_to_real_routes(self):
        cfg = route_intent.load()
        valid_ids = {r["id"] for r in cfg["routes"]}
        for d in cfg["disambiguation"]:
            for rid in d["pair"]:
                self.assertIn(rid, valid_ids, f"disambig pair refs unknown route: {rid}")

    def test_composition_sequences_resolve_to_real_routes(self):
        cfg = route_intent.load()
        valid_ids = {r["id"] for r in cfg["routes"]}
        for c in cfg["composition"]:
            for rid in c["sequence"]:
                self.assertIn(rid, valid_ids, f"composition seq refs unknown route: {rid}")

    def test_match_simplify_routes_to_kiss(self):
        hits = route_intent.match("simplify this function")
        self.assertEqual(hits[0][0], "kiss")

    def test_match_duplicated_routes_to_dry(self):
        hits = route_intent.match("this is duplicated across two places")
        self.assertEqual(hits[0][0], "dry")

    def test_match_train_wreck_routes_to_lod(self):
        hits = route_intent.match("we have train wreck chains")
        self.assertEqual(hits[0][0], "law-of-demeter")

    def test_match_no_signal_returns_empty(self):
        self.assertEqual(route_intent.match("xyzzy"), [])

    def test_disambiguate_known_pair(self):
        rule = route_intent.disambiguate("kiss", "yagni")
        self.assertIsNotNone(rule)
        self.assertIn("ALREADY", rule["rule"])

    def test_disambiguate_unknown_pair_returns_none(self):
        self.assertIsNone(route_intent.disambiguate("kiss", "law-of-demeter"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
