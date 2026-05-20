"""TDD for Phase 8 — post-commit git hook auto-advances workflow state.

Tests invoke the hook script directly (not via real git) with a
planted state.json + schema, then assert the state file was advanced.

Run:
    cd plugins/kaizen && python3 -m unittest tests.test_postcommit_advance -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK = PLUGIN_ROOT / "scripts" / "git-hooks" / "post-commit.sh"


_SCHEMA = """\
name: pc-schema
version: 1
description: post-commit fixture.

artifacts:
  - id: alpha
    generates: a/<x>.md
    template: null
    requires: []
    description: first
    gate: alpha gate

  - id: beta
    generates: b/<x>.md
    template: null
    requires: [alpha]
    description: second
    gate: beta gate

apply:
  gate: beta
  progress: .kaizen/workflow/progress.md
  description: gated on beta
"""


def _plant(root: Path, state: dict | None = None) -> None:
    sd = root / ".kaizen" / "workflow" / "schemas" / "pc-schema"
    sd.mkdir(parents=True)
    (sd / "schema.yaml").write_text(_SCHEMA)
    (root / ".git").mkdir(exist_ok=True)
    if state is not None:
        (root / ".kaizen" / "workflow" / "state.json").write_text(json.dumps(state))


def _run(project_root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "KAIZEN_PROJECT_ROOT_OVERRIDE": str(project_root)}
    return subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True, text=True, env=env, timeout=10,
        cwd=str(project_root),
    )


class TestPostCommitAdvance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_file = self.root / ".kaizen" / "workflow" / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_advances_when_active_workflow(self):
        _plant(self.root, state={
            "schema": "pc-schema", "current_stage": "alpha",
            "completed": [], "remaining": ["beta"], "done": False,
        })
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["current_stage"], "beta")
        self.assertIn("alpha", state["completed"])

    def test_noop_when_no_state(self):
        _plant(self.root, state=None)
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.state_file.exists())

    def test_noop_when_already_done(self):
        _plant(self.root, state={
            "schema": "pc-schema", "current_stage": None,
            "completed": ["alpha", "beta"], "remaining": [], "done": True,
        })
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        # State is unchanged
        self.assertTrue(state["done"])
        self.assertEqual(state["completed"], ["alpha", "beta"])

    def test_disable_env_skips(self):
        _plant(self.root, state={
            "schema": "pc-schema", "current_stage": "alpha",
            "completed": [], "remaining": ["beta"], "done": False,
        })
        env = {**os.environ,
               "KAIZEN_PROJECT_ROOT_OVERRIDE": str(self.root),
               "KAIZEN_POSTCOMMIT_ADVANCE_DISABLE": "1"}
        r = subprocess.run(
            ["bash", str(HOOK)],
            capture_output=True, text=True, env=env, timeout=10,
            cwd=str(self.root),
        )
        self.assertEqual(0, r.returncode, r.stderr)
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["current_stage"], "alpha")  # unchanged


class TestPostCommitProgressRegen(unittest.TestCase):
    """BK-056: the post-commit hook must regen progress.jsonl when
    progress.md was touched in the just-landed commit. Otherwise the
    paired-deliverable convention drifts immediately."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Real git repo — the regen step uses `git diff-tree HEAD` to
        # decide whether to fire, so we need a real HEAD.
        subprocess.run(["git", "init", "-q"], cwd=str(self.root), check=True,
                        capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"],
                        cwd=str(self.root), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"],
                        cwd=str(self.root), check=True, capture_output=True)
        self.md = self.root / ".kaizen" / "workflow" / "progress.md"
        self.md.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, msg: str) -> None:
        subprocess.run(["git", "add", "-A"], cwd=str(self.root),
                        check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", msg],
                        cwd=str(self.root), check=True, capture_output=True)

    def test_regen_fires_when_progress_md_touched(self):
        self.md.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "| 2026-05-20 | feat | +10 | demo row |\n",
            encoding="utf-8",
        )
        self._commit("feat: demo row")
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        jsonl = self.md.with_suffix(".jsonl")
        self.assertTrue(jsonl.is_file(), "post-commit should have regen'd .jsonl")
        lines = [json.loads(ln) for ln in jsonl.read_text().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["summary"], "demo row")

    def test_regen_skips_when_progress_md_not_touched(self):
        # Commit something unrelated — regen must not fire.
        (self.root / "unrelated.txt").write_text("x")
        self._commit("chore: other file")
        r = _run(self.root)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.md.with_suffix(".jsonl").exists())

    def test_disable_env_skips_regen(self):
        self.md.write_text(
            "# Architecture Log\n\n"
            "| Date | Kind | ΔLOC | Summary |\n"
            "|------|------|------|---------|\n"
            "| 2026-05-20 | feat | +10 | demo |\n",
            encoding="utf-8",
        )
        self._commit("feat: demo")
        env = {**os.environ,
               "KAIZEN_PROJECT_ROOT_OVERRIDE": str(self.root),
               "KAIZEN_POSTCOMMIT_PROGRESS_REGEN_DISABLE": "1"}
        r = subprocess.run(
            ["bash", str(HOOK)],
            capture_output=True, text=True, env=env, timeout=10,
            cwd=str(self.root),
        )
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse(self.md.with_suffix(".jsonl").exists())


if __name__ == "__main__":
    unittest.main()
