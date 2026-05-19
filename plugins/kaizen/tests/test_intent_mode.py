"""Tests for the mode/intake intent rules in production intents.yaml.

These load the REAL intents.yaml (not a sandboxed fixture) and verify
the 3 mode-intake rules (start-loop, start-workflow, set-mode-generic)
fire on natural-language phrasing the user is likely to type.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_INTENT_PY = _KZ_DIR / "scripts/intent/intent.py"


class _MatchBase(unittest.TestCase):
    """Calls intent.py suggest with stdin text and parses the envelope."""

    def _suggest(self, text: str) -> dict:
        # Run against the REAL intents.yaml (no KAIZEN_INTENTS_FILE override)
        env = os.environ.copy()
        env.pop("KAIZEN_INTENTS_FILE", None)
        r = subprocess.run(
            [sys.executable, str(_INTENT_PY), "suggest", "--json"],
            input=text, capture_output=True, text=True, timeout=15,
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def _intent_id(self, env: dict) -> str | None:
        data = env.get("data") or {}
        intent = data.get("intent") or {}
        return intent.get("id")


class TestStartLoopIntent(_MatchBase):
    def test_iterate_on_this(self):
        env = self._suggest("let's iterate on this until it works")
        self.assertEqual(self._intent_id(env), "start-loop")

    def test_ralph_this(self):
        env = self._suggest("ralph this task")
        self.assertEqual(self._intent_id(env), "start-loop")

    def test_run_a_loop(self):
        env = self._suggest("can we run a loop on this refactor?")
        self.assertEqual(self._intent_id(env), "start-loop")

    def test_keep_trying_until(self):
        env = self._suggest("keep trying until the tests pass")
        self.assertEqual(self._intent_id(env), "start-loop")


class TestStartWorkflowIntent(_MatchBase):
    def test_use_a_workflow(self):
        env = self._suggest("let's use a workflow for this refactor")
        self.assertEqual(self._intent_id(env), "start-workflow")

    def test_explore_then_plan(self):
        env = self._suggest("first explore the surface then plan the changes")
        self.assertEqual(self._intent_id(env), "start-workflow")

    def test_harden_the_plugin(self):
        env = self._suggest("harden the plugin against bad input")
        self.assertEqual(self._intent_id(env), "start-workflow")

    def test_audit_then_remediate(self):
        env = self._suggest("audit and remediate the 6 HIGH findings")
        self.assertEqual(self._intent_id(env), "start-workflow")


class TestSetModeGenericIntent(_MatchBase):
    def test_what_mode_question(self):
        env = self._suggest("what mode should we use?")
        self.assertEqual(self._intent_id(env), "set-mode-generic")

    def test_configure_session(self):
        env = self._suggest("configure this session please")
        self.assertEqual(self._intent_id(env), "set-mode-generic")

    def test_pin_disciplines(self):
        env = self._suggest("pin disciplines for the whole session")
        self.assertEqual(self._intent_id(env), "set-mode-generic")


class TestAllSuggestionsRouteToWorkflowCommand(_MatchBase):
    """All three mode intents must suggest a /kaizen:workflow invocation
    (the agent surfaces the command verbatim to the user). The retired
    /kaizen:session-mode slash folded into /kaizen:workflow's session
    scope — the picker's Q1 = 'This session only' branch."""

    def test_start_loop_suggests_workflow(self):
        env = self._suggest("iterate on this")
        suggest = env["data"]["intent"]["action"]["suggest"]
        self.assertIn("/kaizen:workflow", suggest)
        # Must NOT regress to the retired slash
        # The suggestion may mention `/kaizen:session-mode` in a historical
        # ("replaces retired ...") note — what matters is that the
        # ACTIVE invocation starts with /kaizen:workflow.
        self.assertTrue(
            suggest.lstrip().startswith("/kaizen:workflow"),
            f"suggestion must lead with /kaizen:workflow; got: {suggest!r}",
        )

    def test_start_workflow_suggests_workflow(self):
        env = self._suggest("use a workflow")
        suggest = env["data"]["intent"]["action"]["suggest"]
        self.assertIn("/kaizen:workflow", suggest)
        # The suggestion may mention `/kaizen:session-mode` in a historical
        # ("replaces retired ...") note — what matters is that the
        # ACTIVE invocation starts with /kaizen:workflow.
        self.assertTrue(
            suggest.lstrip().startswith("/kaizen:workflow"),
            f"suggestion must lead with /kaizen:workflow; got: {suggest!r}",
        )

    def test_set_mode_generic_suggests_workflow_full_qa(self):
        env = self._suggest("set mode")
        suggest = env["data"]["intent"]["action"]["suggest"]
        self.assertIn("/kaizen:workflow", suggest)
        # The suggestion may mention `/kaizen:session-mode` in a historical
        # ("replaces retired ...") note — what matters is that the
        # ACTIVE invocation starts with /kaizen:workflow.
        self.assertTrue(
            suggest.lstrip().startswith("/kaizen:workflow"),
            f"suggestion must lead with /kaizen:workflow; got: {suggest!r}",
        )


class TestCodeTourIntent(_MatchBase):
    """User asks for a code walkthrough → suggest /kaizen:code-tour."""

    def test_walk_me_through(self):
        env = self._suggest("walk me through this codebase")
        self.assertEqual(self._intent_id(env), "code-tour-suggest")

    def test_tour_this_pr(self):
        env = self._suggest("can you tour this PR for me?")
        self.assertEqual(self._intent_id(env), "code-tour-suggest")

    def test_onboarding_doc(self):
        env = self._suggest("write an onboarding tour for new contributors")
        self.assertEqual(self._intent_id(env), "code-tour-suggest")


class TestKarpathyReviewIntent(_MatchBase):
    """User wants a diff-level review → suggest /kaizen:karpathy-check."""

    def test_review_my_diff(self):
        env = self._suggest("review my diff before commit")
        self.assertEqual(self._intent_id(env), "karpathy-review")

    def test_is_this_overcomplicated(self):
        env = self._suggest("is this overcomplicated?")
        self.assertEqual(self._intent_id(env), "karpathy-review")

    def test_check_complexity(self):
        env = self._suggest("check complexity of these files")
        self.assertEqual(self._intent_id(env), "karpathy-review")


class TestSelfImprovingCurateIntent(_MatchBase):
    """User wants to curate auto-memory → suggest /kaizen:self-improving."""

    def test_what_have_i_learned(self):
        env = self._suggest("what has Claude learned this week?")
        self.assertEqual(self._intent_id(env), "self-improving-curate")

    def test_promote_this(self):
        env = self._suggest("promote this learning to a rule")
        self.assertEqual(self._intent_id(env), "self-improving-curate")

    def test_memory_health(self):
        env = self._suggest("check memory health")
        self.assertEqual(self._intent_id(env), "self-improving-curate")


class TestNonMatchingPhrasesDontMisfire(_MatchBase):
    """Sanity: random sentences shouldn't trigger a mode intent."""

    def test_simple_question_no_mode_match(self):
        env = self._suggest("what's 2 plus 2?")
        intent_id = self._intent_id(env)
        if intent_id is not None:
            self.assertNotIn("mode", intent_id,
                              f"unexpected mode intent fired: {intent_id}")

    def test_file_read_no_mode_match(self):
        env = self._suggest("please read the README")
        intent_id = self._intent_id(env)
        if intent_id is not None:
            self.assertNotIn("mode", intent_id,
                              f"unexpected mode intent fired: {intent_id}")


if __name__ == "__main__":
    unittest.main()
