"""Security regression tests — lint_fix_dispatch `git apply` scope (M1).

`_apply_patch` runs `git apply --3way` on an LLM-generated unified
diff. Without a scope check, a prompt-injected local LLM can return
a diff that touches paths OUTSIDE the lint findings — `.github/`,
`.kaizen/hooks/`, `bin/`, anything in the repo.

This test class:
  1. Crafts an LLM-style diff that targets `.github/workflows/ci.yml`
     while the original finding was for `src/foo.py`.
  2. Asserts `_apply_patch` (or a new `_diff_scope_ok` guard) rejects.
  3. Asserts a diff targeting EXACTLY the finding's file is allowed.

Written test-first per TDD. Pre-fix the first test fails (any diff
is applied). Post-fix the scope-validator rejects out-of-scope diffs.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_KZ_DIR / "scripts/lint"))

import lint_fix_dispatch as lfd  # noqa: E402

def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: push\njobs: {}\n")
    (repo / "src").mkdir()
    (repo / "src" / "foo.py").write_text("def f():\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

_LEGIT_DIFF_FOR_FOO_PY = """\
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,2 +1,2 @@
 def f():
-    pass
+    return None
"""

_MALICIOUS_DIFF_TARGETING_CI = """\
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,3 +1,5 @@
 name: ci
 on: push
-jobs: {}
+jobs:
+  pwn:
+    runs-on: ubuntu-latest
"""

_MIXED_LEGIT_AND_MALICIOUS = (_LEGIT_DIFF_FOR_FOO_PY + "\n"
                                + _MALICIOUS_DIFF_TARGETING_CI)

class DiffScopeGuard(unittest.TestCase):
    """A scope guard helper must exist (we'll add `_diff_targets()` +
    `_diff_in_scope(diff, allowed)` to lint_fix_dispatch)."""

    def test_diff_targets_returns_set_of_target_paths(self):
        targets = lfd._diff_targets(_LEGIT_DIFF_FOR_FOO_PY)
        self.assertEqual(targets, {"src/foo.py"})

    def test_diff_targets_handles_multiple_files(self):
        targets = lfd._diff_targets(_MIXED_LEGIT_AND_MALICIOUS)
        self.assertEqual(targets, {"src/foo.py", ".github/workflows/ci.yml"})

    def test_diff_in_scope_allows_when_targets_subset_of_allowed(self):
        self.assertTrue(lfd._diff_in_scope(_LEGIT_DIFF_FOR_FOO_PY,
                                           {"src/foo.py"}))

    def test_diff_in_scope_rejects_when_targets_exceed_allowed(self):
        self.assertFalse(lfd._diff_in_scope(_MALICIOUS_DIFF_TARGETING_CI,
                                             {"src/foo.py"}))

    def test_diff_in_scope_rejects_mixed_legit_plus_out_of_scope(self):
        self.assertFalse(lfd._diff_in_scope(_MIXED_LEGIT_AND_MALICIOUS,
                                             {"src/foo.py"}))

class ApplyPatchScopeEnforced(unittest.TestCase):
    """`_apply_patch(diff, repo, allowed_paths)` must enforce scope."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _init_repo(self.repo)
        self.original_ci = (self.repo / ".github" / "workflows" / "ci.yml").read_text()

    def tearDown(self):
        self._tmp.cleanup()

    def test_apply_rejects_out_of_scope_diff(self):
        # Caller declared the finding was for foo.py; diff touches ci.yml.
        ok = lfd._apply_patch(_MALICIOUS_DIFF_TARGETING_CI, str(self.repo),
                              allowed_paths={"src/foo.py"})
        self.assertFalse(ok, "must refuse a diff outside allowed_paths")
        # ci.yml content MUST NOT have changed
        self.assertEqual(
            (self.repo / ".github" / "workflows" / "ci.yml").read_text(),
            self.original_ci,
            "ci.yml was modified — out-of-scope diff was applied")

    def test_apply_allows_in_scope_diff(self):
        ok = lfd._apply_patch(_LEGIT_DIFF_FOR_FOO_PY, str(self.repo),
                              allowed_paths={"src/foo.py"})
        self.assertTrue(ok, "in-scope diff should apply cleanly")
        # foo.py was modified
        self.assertIn("return None",
                      (self.repo / "src" / "foo.py").read_text())

    def test_apply_rejects_mixed_legit_and_malicious(self):
        ok = lfd._apply_patch(_MIXED_LEGIT_AND_MALICIOUS, str(self.repo),
                              allowed_paths={"src/foo.py"})
        self.assertFalse(ok, "any out-of-scope target poisons the patch")
        # Neither file should have changed
        self.assertEqual(
            (self.repo / ".github" / "workflows" / "ci.yml").read_text(),
            self.original_ci)

if __name__ == "__main__":
    unittest.main()
