"""Tests for ci-gate.sh — the local CI-equivalent merge gate."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
CI_GATE = PLUGIN / "skills" / "workflow" / "scripts" / "ci-gate.sh"
REPO = PLUGIN.parent.parent  # ~/workspace/kaizen-md


class TestCiGate(unittest.TestCase):
    def test_ci_gate_script_exists_and_is_bash(self):
        self.assertTrue(CI_GATE.is_file())
        r = subprocess.run(["bash", "-n", str(CI_GATE)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_ci_gate_runs_syntax_only_mode_clean(self):
        # --syntax-only skips the slow unittest suite; the static checks
        # (bash -n / py parse / json / frontmatter) must pass on HEAD.
        r = subprocess.run(["bash", str(CI_GATE), "--syntax-only"],
                           cwd=REPO, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0,
                         f"static CI checks should pass on HEAD\n{r.stdout}\n{r.stderr}")


class TestCiGateRoutineWiring(unittest.TestCase):
    def test_stage_skill_map_has_ci_gate(self):
        text = (PLUGIN / "skills" / "workflow" / "domain" / "routines.yaml").read_text()
        self.assertIn("ci-gate: kaizen:ci-gate", text)

    def test_code_landing_routines_include_ci_gate_stage(self):
        import yaml  # PyYAML is a CI dependency
        data = yaml.safe_load(
            (PLUGIN / "skills" / "workflow" / "domain" / "routines.yaml").read_text())
        by_name = {r["name"]: r for r in data["routines"]}
        for routine in ("build-feature", "fix-bug", "refactor", "migrate", "harden"):
            self.assertIn("ci-gate", by_name[routine]["stages"],
                          f"{routine} should run ci-gate before landing")


if __name__ == "__main__":
    unittest.main()
