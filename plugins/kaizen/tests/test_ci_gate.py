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
        rc, out, err, _ = _run(["--syntax-only"])
        self.assertEqual(
            rc, 0,
            f"static CI checks should pass on HEAD\n{out}\n{err}",
        )


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


# ─── A + B refactor TDD (agent-callable fast default + glob discovery) ───


import os
import time


def _run(args: list[str], extra_env: dict | None = None) -> tuple[int, str, str, float]:
    """Invoke ci-gate.sh; return (rc, stdout, stderr, elapsed_seconds)."""
    env = {**os.environ, **(extra_env or {})}
    t0 = time.time()
    proc = subprocess.run(
        ["bash", str(CI_GATE), *args],
        capture_output=True, text=True, timeout=120, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr, time.time() - t0


class TestDefaultIsSyntaxOnly(unittest.TestCase):
    """A — bare invocation skips the slow unittest suite.
    Pre-refactor, bare invocation ran the full ~80s suite. Post-refactor
    static-only is the default; caller opts INTO unittests via --full
    or KAIZEN_CI_GATE_FULL=1.

    All 3 tests assert different facets of the SAME `_run([])` output.
    Cached via setUpClass — one invocation amortized across 3 asserts
    (was 3 × ~750ms = ~2.3s; now 1 × ~750ms).
    """

    @classmethod
    def setUpClass(cls):
        cls._rc, cls._out, cls._err, cls._elapsed = _run([])

    def test_default_skips_unittests(self):
        self.assertEqual(self._rc, 0,
                          f"default invocation must pass (got rc={self._rc})")
        self.assertNotIn("unittest suite", self._out,
                          "default must NOT run the unittest suite")
        self.assertLess(self._elapsed, 30.0,
                         f"default must be fast (got {self._elapsed:.1f}s)")

    def test_default_runs_static_checks(self):
        for marker in ("shell scripts parse", "python scripts parse",
                        "json manifests valid", "SKILL.md frontmatter"):
            self.assertIn(marker, self._out, f"default missing: {marker!r}")

    def test_default_emits_indicator(self):
        """Output must explain that unittests were skipped (so the user
        knows to pass --full when they want them)."""
        self.assertRegex(self._out.lower(), r"static|--full|unittests? skipped")


class TestFullOptIn(unittest.TestCase):
    """A — --full or KAIZEN_CI_GATE_FULL=1 runs the unittest suite.

    These tests are EXPENSIVE (~80s each — they actually run the unittest
    suite end-to-end). Skipped by default to keep the routine suite fast;
    opt in via KAIZEN_TEST_CI_GATE_SLOW=1.

    Also skipped when running INSIDE a ci-gate --full run
    (KAIZEN_CI_GATE_RECURSION=1) — those test bodies would spawn another
    ci-gate --full → infinite loop.
    """

    def setUp(self):
        if os.environ.get("KAIZEN_CI_GATE_RECURSION") == "1":
            self.skipTest("running inside ci-gate --full — skip to prevent recursion")
        if os.environ.get("KAIZEN_TEST_CI_GATE_SLOW") != "1":
            self.skipTest("slow integration test — set KAIZEN_TEST_CI_GATE_SLOW=1 to run")

    def test_full_flag_runs_unittests(self):
        rc, out, _, _ = _run(["--full"])
        self.assertEqual(rc, 0)
        self.assertIn("unittest suite", out,
                       "--full must run the unittest suite")

    def test_env_knob_runs_unittests(self):
        rc, out, _, _ = _run([], extra_env={"KAIZEN_CI_GATE_FULL": "1"})
        self.assertEqual(rc, 0)
        self.assertIn("unittest suite", out,
                       "KAIZEN_CI_GATE_FULL=1 must run the unittest suite")


class TestSyntaxOnlyBackcompat(unittest.TestCase):
    """A — --syntax-only flag preserved for back-compat (same as default now)."""

    def test_syntax_only_still_works(self):
        rc, out, _, _ = _run(["--syntax-only"])
        self.assertEqual(rc, 0)
        self.assertNotIn("unittest suite", out)


class TestGlobDiscovery(unittest.TestCase):
    """B — shell-script discovery via glob, not hardcoded paths.

    Pre-refactor: only `scripts/*.sh + hooks/*.sh + hooks/claude/*.sh
    + bin/*` were checked. Scripts in `hooks/codex/`, `skills/loop/scripts/`
    etc. silently escaped. Post-refactor: ALL *.sh under plugins/kaizen/
    get bash -n.
    """

    def _seed_syntax_error_and_check(self, target: Path):
        """Seed a syntax error, run ci-gate, restore. Returns ci-gate rc."""
        original = target.read_text()
        try:
            target.write_text(original + "\nif then fi\n")
            rc, _, _, _ = _run([])
            return rc
        finally:
            target.write_text(original)

    def test_codex_hooks_are_covered(self):
        codex_dir = REPO / "plugins/kaizen/hooks/codex"
        if not codex_dir.is_dir():
            self.skipTest("no hooks/codex dir")
        shells = list(codex_dir.glob("*.sh"))
        if not shells:
            self.skipTest("no *.sh in hooks/codex")
        rc = self._seed_syntax_error_and_check(shells[0])
        self.assertNotEqual(rc, 0,
                             f"glob discovery should catch syntax error in "
                             f"{shells[0].name}")

    def test_loop_scripts_are_covered(self):
        loop_dir = REPO / "plugins/kaizen/skills/loop/scripts"
        if not loop_dir.is_dir():
            self.skipTest("no skills/loop/scripts dir")
        shells = list(loop_dir.glob("*.sh"))
        if not shells:
            self.skipTest("no *.sh in skills/loop/scripts")
        rc = self._seed_syntax_error_and_check(shells[0])
        self.assertNotEqual(rc, 0,
                             f"glob discovery should catch syntax error in "
                             f"{shells[0].name}")


# ─── Polish: 4-fix discipline audit (kiss/dry/boy-scout/karpathy) ────


class TestPolishCarpathy(unittest.TestCase):
    """karpathy — the WHY of KAIZEN_CI_GATE_RECURSION=1 must live next
    to its set site in ci-gate.sh, not only in the test docstring."""

    def test_recursion_env_set_has_inline_why(self):
        text = CI_GATE.read_text()
        self.assertIn("KAIZEN_CI_GATE_RECURSION=1", text)
        # Within 5 lines of the set, the word 'recursion' OR 'infinite' MUST appear.
        lines = text.splitlines()
        set_line = next(i for i, ln in enumerate(lines)
                         if "KAIZEN_CI_GATE_RECURSION=1" in ln)
        window = "\n".join(lines[max(0, set_line - 5):set_line + 1]).lower()
        self.assertRegex(
            window, r"recurs|infinite|loop|guard",
            "karpathy: KAIZEN_CI_GATE_RECURSION needs an inline why-comment "
            f"(found no recursion/infinite-loop note in lines "
            f"{max(0, set_line - 5)}–{set_line})",
        )


class TestPolishKiss(unittest.TestCase):
    """kiss — `--syntax-only` is a no-op alias post-refactor. Mark it
    for retirement so a future scout removes the redundant surface."""

    def test_syntax_only_marked_deprecated(self):
        text = CI_GATE.read_text()
        # Find the --syntax-only branch in the case statement
        self.assertIn("--syntax-only", text)
        # Expect a retire/alias/deprecat marker in the comment block
        # near the case or in the header docstring.
        self.assertRegex(
            text.lower(),
            r"alias of default|kept for back-compat|retire|deprecat",
            "kiss: `--syntax-only` should carry a 'kept for back-compat / "
            "retire after deprecation' marker",
        )


class TestPolishBoyScout(unittest.TestCase):
    """boy-scout — commands/ci-gate.md was touched; while we're here
    its frontmatter description should have ≥3 quoted trigger phrases
    (per the frontmatter-coverage axis I shipped earlier)."""

    def test_command_description_has_three_quoted_triggers(self):
        cmd = PLUGIN / "commands" / "ci-gate.md"
        text = cmd.read_text()
        import re as _re
        # Match `description:` line (multi-line until next ^key:)
        m = _re.search(r"^description:\s*(.+?)(?=^\w+:|^---)",
                        text, _re.MULTILINE | _re.DOTALL)
        desc = m.group(1) if m else ""
        # Count quoted phrases (single or double quotes, ≥2 chars)
        quoted = _re.findall(r'"[^"\n]{2,}"|\'[^\'\n]{2,}\'', desc)
        self.assertGreaterEqual(
            len(quoted), 3,
            f"boy-scout: commands/ci-gate.md description has {len(quoted)} "
            "quoted trigger phrases (<3 = weak-routing per frontmatter axis). "
            f"Found: {quoted}",
        )


class TestPolishDry(unittest.TestCase):
    """dry — the pre-existing TestCiGate's --syntax-only invocation
    duplicates the _run() helper used by the new test classes. Retrofit
    pinned here so the helper has 1 invoker class fewer to track."""

    def test_pre_existing_class_uses_run_helper(self):
        """The pre-existing class's --syntax-only test should call _run()
        instead of inline subprocess.run — single helper for the file."""
        text = Path(__file__).read_text()
        # Find the body of test_ci_gate_runs_syntax_only_mode_clean
        import re as _re
        m = _re.search(
            r"def test_ci_gate_runs_syntax_only_mode_clean\(self\):\n(.*?)\n    def ",
            text, _re.DOTALL,
        )
        body = m.group(1) if m else ""
        self.assertIn("_run(", body,
                       "dry: pre-existing test must reuse the _run() helper "
                       "rather than inline subprocess.run([..., '--syntax-only'])")


if __name__ == "__main__":
    unittest.main()
