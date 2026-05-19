"""RED first — lint_fix_dispatch tests.

Dispatcher for ruff/ty findings. Two strategies:

  strategy='subagent'  — emit a structured task spec dict per
                          finding-group (one per file). Caller (Claude
                          session) consumes via the Agent tool. No I/O.
  strategy='local_llm' — POST to an OpenAI-compatible chat endpoint,
                          extract a unified diff from the response,
                          apply if `apply=True`. Pure HTTP boundary.

Both strategies share the same input shape (list of findings from
lint_mcp's `_normalize_ruff` / `_parse_ty_concise`) and return a
DispatchResult dict.

Run:
    python3 -m unittest tests.test_lint_fix_dispatch -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "mcp"))

import lint_fix_dispatch as lfd  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────────────

def _sample_ruff_findings() -> list[dict]:
    """Same shape lint_mcp._normalize_ruff produces."""
    return [
        {
            "severity": "error", "code": "F401",
            "file": "src/foo.py", "line": 3, "col": 1,
            "message": "imported but unused: os",
            "fix_available": True,
        },
        {
            "severity": "error", "code": "E501",
            "file": "src/foo.py", "line": 12, "col": 1,
            "message": "line too long (102 > 100)",
            "fix_available": False,
        },
        {
            "severity": "error", "code": "B017",
            "file": "src/bar.py", "line": 50, "col": 8,
            "message": "Do not assert blind exception",
            "fix_available": False,
        },
    ]


def _sample_ty_findings() -> list[dict]:
    return [
        {
            "severity": "error", "code": "invalid-method-override",
            "file": "src/foo.py", "line": 7, "col": 5,
            "message": "Invalid override of method `prep_async`",
        },
    ]


# ─── T1 Unit — strategy validation + grouping ─────────────────────────

class StrategyValidation(unittest.TestCase):

    def test_dispatch_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            lfd.dispatch(_sample_ruff_findings(), strategy="bogus", repo_root=".")

    def test_dispatch_rejects_empty_strategy(self):
        with self.assertRaises(ValueError):
            lfd.dispatch(_sample_ruff_findings(), strategy="", repo_root=".")

    def test_dispatch_accepts_subagent_strategy(self):
        out = lfd.dispatch(_sample_ruff_findings(), strategy="subagent",
                            repo_root=".")
        self.assertEqual(out["strategy"], "subagent")

    def test_dispatch_returns_empty_when_no_findings(self):
        out = lfd.dispatch([], strategy="subagent", repo_root=".")
        self.assertEqual(out["dispatched_count"], 0)
        self.assertEqual(out["tasks"], [])

    def test_dispatch_filters_to_unfixable_when_ruff_already_handles(self):
        """ruff --fix already handles `fix_available=True` findings; the
        dispatcher should ONLY ship the ones ruff can't auto-fix
        (default skip_ruff_fixable=True)."""
        out = lfd.dispatch(
            _sample_ruff_findings(),
            strategy="subagent",
            repo_root=".",
            skip_ruff_fixable=True,
        )
        # Findings with fix_available=True dropped → 2 remain (E501 + B017)
        all_codes = [
            f["code"]
            for t in out["tasks"]
            for f in t["findings"]
        ]
        self.assertNotIn("F401", all_codes)
        self.assertIn("E501", all_codes)
        self.assertIn("B017", all_codes)

    def test_dispatch_can_include_ruff_fixable_when_opted_in(self):
        out = lfd.dispatch(
            _sample_ruff_findings(),
            strategy="subagent",
            repo_root=".",
            skip_ruff_fixable=False,
        )
        all_codes = [
            f["code"]
            for t in out["tasks"]
            for f in t["findings"]
        ]
        self.assertIn("F401", all_codes)


class FindingGrouping(unittest.TestCase):

    def test_findings_grouped_by_file(self):
        out = lfd.dispatch(_sample_ruff_findings(), strategy="subagent",
                            repo_root=".", skip_ruff_fixable=False)
        # 3 findings, 2 files → 2 tasks
        self.assertEqual(len(out["tasks"]), 2)
        files = sorted(t["file"] for t in out["tasks"])
        self.assertEqual(files, ["src/bar.py", "src/foo.py"])

    def test_ruff_and_ty_findings_merge_in_same_task_per_file(self):
        merged = _sample_ruff_findings() + _sample_ty_findings()
        out = lfd.dispatch(merged, strategy="subagent", repo_root=".",
                            skip_ruff_fixable=False)
        # src/foo.py has both ruff + ty findings
        foo_task = next(t for t in out["tasks"] if t["file"] == "src/foo.py")
        codes = {f["code"] for f in foo_task["findings"]}
        self.assertTrue({"F401", "E501", "invalid-method-override"} <= codes)


# ─── T1 Unit — subagent task spec rendering ───────────────────────────

class SubagentTaskSpec(unittest.TestCase):

    def test_task_spec_has_required_fields(self):
        out = lfd.dispatch(_sample_ruff_findings(), strategy="subagent",
                            repo_root=".", skip_ruff_fixable=False)
        for task in out["tasks"]:
            self.assertIn("file", task)
            self.assertIn("findings", task)
            self.assertIn("prompt", task)
            self.assertIn("description", task)

    def test_task_prompt_includes_all_findings_for_the_file(self):
        out = lfd.dispatch(_sample_ruff_findings(), strategy="subagent",
                            repo_root=".", skip_ruff_fixable=False)
        foo_task = next(t for t in out["tasks"] if t["file"] == "src/foo.py")
        # F401 + E501 both appear in the prompt body
        self.assertIn("F401", foo_task["prompt"])
        self.assertIn("E501", foo_task["prompt"])
        self.assertIn("imported but unused", foo_task["prompt"])

    def test_task_description_is_short(self):
        """Per Agent tool docs the description should be 3-5 words."""
        out = lfd.dispatch(_sample_ruff_findings(), strategy="subagent",
                            repo_root=".", skip_ruff_fixable=False)
        for task in out["tasks"]:
            self.assertLessEqual(len(task["description"]), 80)


# ─── T1.5 Contract-verified mocks ─────────────────────────────────────

class ContractMocks(unittest.TestCase):

    def test_dispatch_signature_pins_documented_kwargs(self):
        import inspect
        sig = inspect.signature(lfd.dispatch)
        for name in ("findings", "strategy", "repo_root",
                     "skip_ruff_fixable", "model", "apply"):
            self.assertIn(name, sig.parameters,
                            f"dispatch missing kwarg: {name}")

    def test_local_llm_dispatch_uses_documented_env_vars(self):
        """The local-LLM path must read LLM_BASE_URL + LLM_MODEL (matches
        clever-lama convention). Catches refactor regressions."""
        self.assertIn("LLM_BASE_URL", lfd.DEFAULT_ENV_VARS)
        self.assertIn("LLM_MODEL", lfd.DEFAULT_ENV_VARS)


# ─── T2 Integration — local_llm path (HTTP boundary mocked) ─────────

class LocalLlmDispatch(unittest.TestCase):

    def test_local_llm_posts_one_request_per_file_group(self):
        with mock.patch.object(lfd, "_http_post", autospec=True) as post:
            post.return_value = {
                "choices": [{"message": {"content": "```diff\n--- a\n+++ a\n```"}}]
            }
            out = lfd.dispatch(_sample_ruff_findings(),
                                strategy="local_llm",
                                repo_root=".", skip_ruff_fixable=False,
                                model="test-model", apply=False)
            self.assertEqual(post.call_count, 2)   # 2 files
            self.assertEqual(out["strategy"], "local_llm")
            self.assertEqual(len(out["tasks"]), 2)
            for t in out["tasks"]:
                self.assertIn("patch", t)

    def test_local_llm_does_not_apply_patches_when_apply_false(self):
        with mock.patch.object(lfd, "_http_post", autospec=True) as post, \
             mock.patch.object(lfd, "_apply_patch", autospec=True) as apply:
            post.return_value = {
                "choices": [{"message": {"content": "```diff\n--- a\n+++ b\n```"}}]
            }
            lfd.dispatch(_sample_ruff_findings()[:1],
                         strategy="local_llm", repo_root=".",
                         skip_ruff_fixable=False, apply=False)
            apply.assert_not_called()

    def test_local_llm_applies_patches_when_apply_true(self):
        with mock.patch.object(lfd, "_http_post", autospec=True) as post, \
             mock.patch.object(lfd, "_apply_patch", autospec=True) as apply:
            post.return_value = {
                "choices": [{"message": {"content": "```diff\n--- a\n+++ b\n```"}}]
            }
            apply.return_value = True
            lfd.dispatch(_sample_ruff_findings()[:1],
                         strategy="local_llm", repo_root=".",
                         skip_ruff_fixable=False, apply=True)
            apply.assert_called_once()

    def test_local_llm_records_extraction_failure(self):
        """If the LLM response has no diff fence, dispatcher should
        flag the task as `patch_extraction_failed=True` rather than crash."""
        with mock.patch.object(lfd, "_http_post", autospec=True) as post:
            post.return_value = {
                "choices": [{"message": {"content": "no diff in this output"}}]
            }
            out = lfd.dispatch(_sample_ruff_findings()[:1],
                                strategy="local_llm", repo_root=".",
                                skip_ruff_fixable=False, apply=False)
            self.assertTrue(out["tasks"][0].get("patch_extraction_failed"))


# ─── T2 Integration — patch extraction ────────────────────────────────

class PatchExtraction(unittest.TestCase):

    def test_extract_diff_finds_fenced_diff_block(self):
        text = (
            "Here's the fix:\n\n```diff\n"
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-bad\n+good\n"
            "```\nDone."
        )
        diff = lfd._extract_diff(text)
        self.assertIn("--- a/foo.py", diff)

    def test_extract_diff_finds_unfenced_unified_diff(self):
        text = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-bad\n+good\n"
        )
        diff = lfd._extract_diff(text)
        self.assertIn("--- a/foo.py", diff)

    def test_extract_diff_returns_empty_string_on_garbage(self):
        self.assertEqual(lfd._extract_diff("not a diff at all"), "")


# ─── T3 Regression — lint_mcp surface untouched ───────────────────────

class LintMcpUntouched(unittest.TestCase):

    def test_lint_mcp_still_imports_without_dispatch_module(self):
        """Importing lint_mcp must not now require lint_fix_dispatch
        (the dispatcher is optional / opt-in)."""
        import importlib
        import lint_mcp  # noqa: F401
        importlib.reload(lint_mcp)


if __name__ == "__main__":
    unittest.main()
