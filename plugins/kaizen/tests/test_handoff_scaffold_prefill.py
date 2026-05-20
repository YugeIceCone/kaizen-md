"""Tests for handoff scaffold's path-prefill behavior.

Split from test_handoff_scaffold.py to keep the per-file karpathy
complexity check happy (the parent file went over the 500-line
threshold after the prefill / cap / test-template behaviour set
landed in commits f681c2d / c8b04c1 / 127b746).

Shares the ScaffoldBase fixture by importing it; tests stay
independent + each class targets one behavior:

  TestScaffoldFiltersNonExistentPaths
      Prefill filters created-then-removed-in-same-window paths
      so verify doesn't false-positive 'missing' on intra-session
      consolidations.

  TestScaffoldTestTemplate
      `test:` template auto-fills the runnable kaizen-tests
      invocation when the repo looks like the kaizen-md plugin
      layout (has plugins/kaizen/tests/); falls back to TBD
      elsewhere.

  TestScaffoldFilesCapped
      Synthetic done_this_session files list capped at
      KAIZEN_HANDOFF_FILES_CAP (default 50) with an overflow
      comment recording the truncation. The per-project files: map
      at the bottom stays complete (verify reads it for file
      existence checks).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from test_handoff_scaffold import ScaffoldBase, _HANDOFF_PY  # noqa: E402


class TestScaffoldFiltersNonExistentPaths(ScaffoldBase):
    """Files created-then-deleted within the same since-window are stale
    references — including them in the handoff's files lists causes
    verify to false-positive 'missing' on every consolidation/rename.
    The prefill MUST filter to paths that still exist in the worktree."""

    def test_consolidated_path_excluded_from_done_files(self):
        # Create then delete a path in the same window — simulates a
        # within-session consolidation (e.g. 44 root slashes -> 9 menus).
        self._commit("legacy/old_command.md", "old\n")
        (self.repo / "legacy" / "old_command.md").unlink()
        subprocess.run(["git", "add", "-A"], cwd=str(self.repo),
                        check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "consolidate"],
                        cwd=str(self.repo), check=True, capture_output=True)
        # And a file that does still exist
        self._commit("src/kept.py", "x\n")

        r = self._run(
            "--session", "consol",
            "--goal", "consolidate", "--now", "next",
            "--since", "2000-01-01",
            "--at", "2026-05-20_03-00", "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text()
        self.assertIn("src/kept.py", body)
        self.assertNotIn("legacy/old_command.md", body)

    def test_synthetic_git_touched_uses_one_path_per_line(self):
        # Three files, all still present — prior format dumped them in
        # a single bracketed line that exploded the YAML size.
        # Without JSONL mining the scaffolder takes the `elif changed`
        # branch (task: "TBD (scaffolded — agent fills)") which also
        # must emit per-line files.
        for p in ("a.py", "b.py", "c.py"):
            self._commit(p, "x\n")

        r = self._run(
            "--session", "demo",
            "--goal", "did", "--now", "next",
            "--since", "2000-01-01",
            "--at", "2026-05-20_03-00", "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text()
        # files: are emitted one-per-line, not bracketed.
        self.assertIn("    files:\n      - a.py", body)
        self.assertIn("\n      - b.py", body)
        self.assertIn("\n      - c.py", body)
        self.assertNotIn("files: [a.py, b.py, c.py]", body)


class TestScaffoldTestTemplate(ScaffoldBase):
    """The bare `test: TBD` placeholder routinely got filled with
    `kaizen-tests` (no flags) by agents — which errors with
    'no test files matched' when run from a parent dir. When the
    scaffolder detects the kaizen-md plugin layout, pre-fill a
    runnable invocation that includes --tests-dir."""

    def test_kaizen_md_repo_gets_runnable_test_line(self):
        # Plant the kaizen-md layout marker
        (self.repo / "plugins" / "kaizen" / "tests").mkdir(parents=True)
        self._commit("src/x.py", "x\n")
        r = self._run(
            "--session", "kmd",
            "--goal", "g", "--now", "n",
            "--since", "2000-01-01",
            "--at", "2026-05-20_03-00", "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text()
        self.assertIn("test: kaizen-tests --tests-dir plugins/kaizen/tests", body)
        self.assertNotIn("test: TBD", body)

    def test_non_kaizen_repo_keeps_tbd_placeholder(self):
        # No plugins/kaizen/tests/ in this repo — should keep TBD.
        self._commit("src/x.py", "x\n")
        r = self._run(
            "--session", "other",
            "--goal", "g", "--now", "n",
            "--since", "2000-01-01",
            "--at", "2026-05-20_03-00", "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text()
        self.assertIn("test: TBD", body)


class TestScaffoldFilesCapped(ScaffoldBase):
    """Long sessions can push the synthetic git-touched entry to 200+
    paths — that single block was responsible for ~half of the 1779-line
    2026-05-20 handoff. The scaffolder caps at KAIZEN_HANDOFF_FILES_CAP
    (default 50) and emits a comment line recording the truncation."""

    def test_files_capped_at_default_with_overflow_line(self):
        # 60 files; default cap is 50. The cap only narrows the synthetic
        # done_this_session entry — the per-project files: map at the
        # bottom stays complete (verify uses it for file-existence
        # checks; truncating would defeat the verify contract).
        for i in range(60):
            self._commit(f"f{i:02d}.py", "x\n")
        r = self._run(
            "--session", "many",
            "--goal", "lots", "--now", "next",
            "--since", "2000-01-01",
            "--at", "2026-05-20_03-00", "--json",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text()
        # Extract just the done_this_session block (the synthetic entry's home).
        synthetic_block = body.split("blockers:")[0]
        # First 50 paths present in the synthetic block.
        self.assertIn("\n      - f00.py", synthetic_block)
        self.assertIn("\n      - f49.py", synthetic_block)
        # Path 50+ absent FROM THE SYNTHETIC BLOCK; overflow comment present.
        self.assertNotIn("\n      - f50.py", synthetic_block)
        self.assertIn(
            "# ... +10 more (capped at KAIZEN_HANDOFF_FILES_CAP=50)",
            synthetic_block,
        )

    def test_files_cap_disabled_via_env_zero(self):
        for i in range(5):
            self._commit(f"f{i}.py", "x\n")
        env = os.environ.copy()
        env["KAIZEN_HANDOFF_FILES_CAP"] = "0"
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "scaffold",
             "--session", "nocap",
             "--goal", "x", "--now", "y",
             "--since", "2000-01-01",
             "--at", "2026-05-20_03-00", "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.repo), env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text()
        # All 5 present, no overflow comment
        for i in range(5):
            self.assertIn(f"\n      - f{i}.py", body)
        self.assertNotIn("more (capped", body)


if __name__ == "__main__":
    unittest.main()
