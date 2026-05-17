"""Tests for session_mode.py — the intake-state CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "skills/workflow/scripts/session_mode.py"


class Base(unittest.TestCase):
    def setUp(self):
        self._cwd0 = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state_path = self.tmp / "session-mode.json"
        self._orig = os.environ.get("KAIZEN_SESSION_MODE_PATH")
        os.environ["KAIZEN_SESSION_MODE_PATH"] = str(self.state_path)

    def tearDown(self):
        try: os.chdir(self._cwd0)
        except OSError: pass
        self._tmp.cleanup()
        if self._orig is None: os.environ.pop("KAIZEN_SESSION_MODE_PATH", None)
        else: os.environ["KAIZEN_SESSION_MODE_PATH"] = self._orig

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True, timeout=5,
            env=os.environ.copy(),
        )


class TestSetThenGet(Base):
    def test_set_loop_persists(self):
        r = self._run("set", "loop")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "loop")
        self.assertEqual(data["skills"], [])
        self.assertIn("set_at", data)
        self.assertTrue(self.state_path.is_file())

    def test_set_with_skills_parses_csv(self):
        r = self._run("set", "loop", "--skills", "dry,kiss,tdd")
        data = json.loads(r.stdout)
        self.assertEqual(data["skills"], ["dry", "kiss", "tdd"])

    def test_set_strips_skill_whitespace(self):
        r = self._run("set", "workflow", "--skills", " dry , kiss ,tdd ")
        data = json.loads(r.stdout)
        self.assertEqual(data["skills"], ["dry", "kiss", "tdd"])

    def test_set_session_id(self):
        r = self._run("set", "neither", "--session-id", "abc-123")
        data = json.loads(r.stdout)
        self.assertEqual(data["session_id"], "abc-123")


class TestGet(Base):
    def test_get_returns_mode_when_set(self):
        self._run("set", "workflow")
        r = self._run("get")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "workflow")

    def test_get_json_returns_full_record(self):
        self._run("set", "loop", "--skills", "dry,tdd")
        r = self._run("get", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "loop")
        self.assertEqual(data["skills"], ["dry", "tdd"])

    def test_get_unset_exit_1(self):
        r = self._run("get")
        self.assertEqual(r.returncode, 1)

    def test_get_json_unset_returns_mode_none(self):
        r = self._run("get", "--json")
        self.assertEqual(json.loads(r.stdout)["mode"], None)


class TestExists(Base):
    def test_exists_after_set(self):
        self._run("set", "loop")
        self.assertEqual(self._run("exists").returncode, 0)

    def test_exists_unset_exits_1(self):
        self.assertEqual(self._run("exists").returncode, 1)


class TestClear(Base):
    def test_clear_removes_file(self):
        self._run("set", "loop")
        self.assertTrue(self.state_path.is_file())
        r = self._run("clear")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self.state_path.is_file())

    def test_clear_when_absent_no_error(self):
        # idempotent
        r = self._run("clear")
        self.assertEqual(r.returncode, 0)


class TestInvalidMode(Base):
    def test_unknown_mode_rejected(self):
        r = self._run("set", "garbage")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.state_path.is_file())


class TestBundleExpansion(Base):
    def test_simplicity_expands(self):
        r = self._run("set", "loop", "--bundles", "simplicity")
        data = json.loads(r.stdout)
        self.assertEqual(set(data["skills"]), {"kiss", "yagni", "dry"})
        self.assertEqual(data["bundles"], ["simplicity"])

    def test_structure_expands_full_architecture_family(self):
        r = self._run("set", "loop", "--bundles", "structure")
        data = json.loads(r.stdout)
        # SOLID classics
        self.assertIn("solid", data["skills"])
        self.assertIn("soc", data["skills"])
        self.assertIn("lod", data["skills"])
        # Layered / inward-deps family (the "same vein" as onion-ddd)
        for tag in ("onion-ddd", "hexagonal", "clean-arch",
                     "dip", "bounded-contexts"):
            self.assertIn(tag, data["skills"],
                          f"structure bundle missing {tag!r}")

    def test_structure_bundle_has_no_typo_sof(self):
        """Regression guard: prior 'sof' (typo for soc) shouldn't reappear."""
        r = self._run("set", "loop", "--bundles", "structure")
        data = json.loads(r.stdout)
        self.assertNotIn("sof", data["skills"])

    def test_multiple_bundles_merge(self):
        r = self._run("set", "loop", "--bundles", "simplicity,process")
        data = json.loads(r.stdout)
        s = set(data["skills"])
        self.assertTrue({"kiss", "yagni", "dry"}.issubset(s))
        self.assertTrue({"tdd", "boy-scout", "convention"}.issubset(s))

    def test_bundles_plus_explicit_skills_merge_unique(self):
        # simplicity = kiss + yagni + dry; --skills adds tdd (new) and dry (dup)
        r = self._run("set", "loop",
                       "--bundles", "simplicity",
                       "--skills", "tdd,dry")
        data = json.loads(r.stdout)
        # dry appears once (deduped)
        self.assertEqual(data["skills"].count("dry"), 1)
        self.assertIn("tdd", data["skills"])

    def test_unknown_bundle_silently_dropped(self):
        r = self._run("set", "loop", "--bundles", "simplicity,garbage,karpathy")
        data = json.loads(r.stdout)
        # only the valid two contribute
        self.assertIn("kiss", data["skills"])
        self.assertIn("karpathy", data["skills"])
        # bundles field records what the user PICKED (including the typo —
        # downstream consumers can detect drift if they care)
        self.assertEqual(data["bundles"],
                          ["simplicity", "garbage", "karpathy"])

    def test_skills_lowercased(self):
        r = self._run("set", "loop", "--skills", "KISS,YAGNI")
        data = json.loads(r.stdout)
        self.assertEqual(data["skills"], ["kiss", "yagni"])


class TestBundlesSubcommand(Base):
    def test_lists_coding_skills_bundles(self):
        r = self._run("bundles")
        self.assertEqual(r.returncode, 0)
        for name in ("simplicity", "structure", "process", "karpathy"):
            self.assertIn(name, r.stdout)

    def test_lists_operational_bundles(self):
        """New operational tier — cross-cutting disciplines beyond coding-style."""
        r = self._run("bundles")
        self.assertEqual(r.returncode, 0)
        for name in ("quality", "security", "brain-hygiene", "plugin-dev"):
            self.assertIn(name, r.stdout, f"missing operational bundle {name!r}")

    def test_json_emits_full_mapping(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(
            set(data.keys()),
            {
                # coding-style tier
                "simplicity", "structure", "process", "karpathy",
                # operational tier
                "quality", "security", "brain-hygiene", "plugin-dev",
                # work-mode tier
                "discovery", "debugging", "refactoring", "planning",
            },
        )
        self.assertIn("kiss", data["simplicity"])

    def test_plugin_dev_bundle_includes_plugin_development(self):
        """User-requested: /kaizen:mode must be able to pin plugin-development."""
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("plugin-development", data["plugin-dev"])

    def test_quality_bundle_includes_gatekeeper_and_iron_laws(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("gatekeeper", data["quality"])
        self.assertIn("iron-laws", data["quality"])

    def test_brain_hygiene_bundle_includes_remember(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("remember", data["brain-hygiene"])

    def test_security_bundle_includes_security_review(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("security-review", data["security"])

    def test_lists_work_mode_bundles(self):
        """3rd tier — work-mode bundles for task-specific disciplines."""
        r = self._run("bundles")
        self.assertEqual(r.returncode, 0)
        for name in ("discovery", "debugging", "refactoring", "planning"):
            self.assertIn(name, r.stdout, f"missing work-mode bundle {name!r}")

    def test_discovery_bundle_includes_brainstorming(self):
        """User-requested: brainstorming is pin-able via /kaizen:mode."""
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("brainstorming", data["discovery"])

    def test_debugging_bundle_includes_systematic_debugging(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("systematic-debugging", data["debugging"])

    def test_refactoring_bundle_includes_boy_scout(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("boy-scout", data["refactoring"])

    def test_planning_bundle_includes_writing_plans(self):
        r = self._run("bundles", "--json")
        data = json.loads(r.stdout)
        self.assertIn("writing-plans", data["planning"])


class TestReminderSubcommand(Base):
    def test_no_state_empty_output(self):
        r = self._run("reminder")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_state_without_skills_empty_output(self):
        self._run("set", "neither")  # no --bundles, no --skills
        r = self._run("reminder")
        self.assertEqual(r.stdout, "")

    def test_loop_with_simplicity_bundle_reminds_three_skills(self):
        self._run("set", "loop", "--bundles", "simplicity")
        r = self._run("reminder")
        self.assertEqual(r.returncode, 0)
        self.assertIn("kaizen disciplines pinned:", r.stdout)
        self.assertIn("kiss", r.stdout)
        self.assertIn("yagni", r.stdout)
        self.assertIn("dry", r.stdout)
        # Each pinned skill must come with its description
        self.assertIn("keep it simple", r.stdout)

    def test_unknown_skill_silently_dropped(self):
        """Skills not in _SKILL_DESCRIPTIONS are skipped (typo resilience)."""
        self._run("set", "loop", "--skills", "kiss,future-skill-xyz,dry")
        r = self._run("reminder")
        self.assertIn("kiss", r.stdout)
        self.assertIn("dry", r.stdout)
        self.assertNotIn("future-skill-xyz", r.stdout)

    def test_json_output(self):
        self._run("set", "loop", "--bundles", "simplicity")
        r = self._run("reminder", "--json")
        data = json.loads(r.stdout)
        ids = [s["id"] for s in data["skills"]]
        self.assertEqual(set(ids), {"kiss", "yagni", "dry"})
        for s in data["skills"]:
            self.assertIn("description", s)
            self.assertGreater(len(s["description"]), 5)


class TestSkillDescriptionsCatalog(Base):
    """All bundled skills MUST have a description — otherwise the
    reminder hook silently skips them and the user wonders why
    their pin doesn't surface."""

    def test_every_bundled_skill_has_a_description(self):
        # Discover all skills from the bundle catalog
        r = self._run("bundles", "--json")
        bundles = json.loads(r.stdout)
        all_bundled = set()
        for skills in bundles.values():
            all_bundled.update(skills)
        # Pin every bundled skill, ensure the reminder includes ALL of them
        self._run("set", "loop", "--skills", ",".join(all_bundled))
        r = self._run("reminder", "--json")
        reminded = {s["id"] for s in json.loads(r.stdout)["skills"]}
        missing = all_bundled - reminded
        self.assertEqual(missing, set(),
                          f"bundled skills with no _SKILL_DESCRIPTIONS entry: {missing}")


class TestAutoHandoffThreshold(Base):
    def test_threshold_75_persists(self):
        r = self._run("set", "loop", "--threshold", "75")
        data = json.loads(r.stdout)
        self.assertEqual(data["auto_handoff_threshold"], 75)

    def test_threshold_omitted_defaults_to_none(self):
        r = self._run("set", "loop")
        data = json.loads(r.stdout)
        self.assertIsNone(data["auto_handoff_threshold"])

    def test_invalid_threshold_rejected(self):
        # 50 is valid, 33 is not
        r = self._run("set", "loop", "--threshold", "33")
        self.assertNotEqual(r.returncode, 0)

    def test_valid_thresholds_25_50_75_85(self):
        for v in (25, 50, 75, 85):
            r = self._run("set", "loop", "--threshold", str(v))
            data = json.loads(r.stdout)
            self.assertEqual(data["auto_handoff_threshold"], v)


class TestThresholdSubcommand(Base):
    def test_threshold_subcommand_prints_value_when_set(self):
        self._run("set", "loop", "--threshold", "85")
        r = self._run("threshold")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "85")

    def test_threshold_subcommand_exits_1_when_unset(self):
        self._run("set", "loop")  # no --threshold
        r = self._run("threshold")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")

    def test_threshold_subcommand_exits_1_when_no_state(self):
        # No prior set
        r = self._run("threshold")
        self.assertEqual(r.returncode, 1)


class TestModeOverwrite(Base):
    """set replaces prior state — no implicit merge."""
    def test_second_set_overwrites_first(self):
        self._run("set", "loop", "--skills", "dry")
        self._run("set", "workflow", "--skills", "tdd")
        r = self._run("get", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["mode"], "workflow")
        self.assertEqual(data["skills"], ["tdd"])


if __name__ == "__main__":
    unittest.main()
