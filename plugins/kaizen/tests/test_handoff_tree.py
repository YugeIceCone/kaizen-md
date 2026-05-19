"""Tests for `kaizen handoff tree` — commit↔task bidirectional map.

Per Task #40 (handoff upgrades) — 3 of 6 shipped. Walks
done_this_session entries that have `files: [...]` attached; for each
entry runs `_auto_tag_commits` to list commits since the handoff date
that touched any of those files. Emits a bidirectional JSON map.

Used to answer:
  - "Which task did commit <sha> advance?"
  - "Which commits advanced the <task> arc?"

Entries without files: surfaced under `skipped_no_files` (can't be
tree-mapped without file paths).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
_HANDOFF = _KZ / "skills/workflow/scripts/handoff.py"

sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))
import handoff as _h  # noqa: E402


_BASE_YAML = """---
session: test-repo
date: 2026-05-18
status: complete
outcome: PARTIAL_PLUS
---

session_meta:
  handoff_generated_at: '2026-05-18T20:00:00Z'

goal: 'test tree map'
now: 'verify the tree command works'
test: pytest

done_this_session:
  - task: 'wired feature A'
    files: ['src/a.py']
  - task: 'wired feature B'
    files: ['src/b.py', 'tests/test_b.py']
  - task: 'wrote docs only'
    files: []
  - task: 'no files attached'

blockers: []
"""


def _init_repo_with_commits(repo: Path) -> dict[str, str]:
    """Return mapping of {file → sha that introduced it}."""
    for cmd in (["git", "init", "-q", "-b", "main"],
                 ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=str(repo), check=True, capture_output=True)
    shas = {}
    # 3 commits, each touching distinct files
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    for fpath, msg in (
        ("src/a.py", "feat(a): impl A"),
        ("src/b.py", "feat(b): impl B"),
        ("tests/test_b.py", "test(b): cover B"),
    ):
        (repo / fpath).write_text(f"# {fpath}\n")
        subprocess.run(["git", "add", fpath], cwd=str(repo), check=True,
                        capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", msg],
                        cwd=str(repo), check=True, capture_output=True)
        # Match `_auto_tag_commits` which uses git's default %h length
        r = subprocess.run(["git", "log", "-1", "--format=%h"],
                            cwd=str(repo), capture_output=True, text=True)
        shas[fpath] = r.stdout.strip()
    return shas


# ─── _build_commit_task_map (pure function) ────────────────────────────

class TestBuildCommitTaskMap(unittest.TestCase):
    def test_maps_files_to_commits_bidirectionally(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            shas = _init_repo_with_commits(repo)
            entries = [
                {"task": "wired A", "files": ["src/a.py"]},
                {"task": "wired B", "files": ["src/b.py", "tests/test_b.py"]},
            ]
            r = _h._build_commit_task_map(entries, repo=repo, since="2020-01-01")
            # by_task — each entry's commits
            self.assertEqual(r["by_task"]["wired A"], [shas["src/a.py"]])
            # B touches 2 files in 2 commits
            self.assertEqual(set(r["by_task"]["wired B"]),
                              {shas["src/b.py"], shas["tests/test_b.py"]})
            # by_commit — each sha lists tasks it advanced
            self.assertEqual(r["by_commit"][shas["src/a.py"]], ["wired A"])
            self.assertEqual(r["by_commit"][shas["src/b.py"]], ["wired B"])
            self.assertEqual(r["by_commit"][shas["tests/test_b.py"]], ["wired B"])
            # Entries with no files (or no commits) surface separately
            self.assertEqual(r["skipped_no_files"], [])

    def test_entries_without_files_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_repo_with_commits(repo)
            entries = [
                {"task": "docs only", "files": []},
                {"task": "no files key"},
            ]
            r = _h._build_commit_task_map(entries, repo=repo, since="2020-01-01")
            self.assertEqual(set(r["skipped_no_files"]),
                              {"docs only", "no files key"})
            self.assertEqual(r["by_task"], {})
            self.assertEqual(r["by_commit"], {})

    def test_one_commit_advancing_multiple_tasks(self):
        # If 2 tasks touch the same file, the commit shows in BOTH by_task
        # entries + by_commit lists both tasks.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            shas = _init_repo_with_commits(repo)
            entries = [
                {"task": "task 1", "files": ["src/a.py"]},
                {"task": "task 2", "files": ["src/a.py"]},
            ]
            r = _h._build_commit_task_map(entries, repo=repo, since="2020-01-01")
            sha = shas["src/a.py"]
            self.assertEqual(set(r["by_commit"][sha]), {"task 1", "task 2"})


# ─── CLI integration ───────────────────────────────────────────────────

class TestTreeCLI(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.shas = _init_repo_with_commits(self.repo)
        self.yaml = self.repo / "handoff.yaml"
        self.yaml.write_text(_BASE_YAML, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "GIT_DIR"}
        return subprocess.run(
            [sys.executable, str(_HANDOFF), *args],
            capture_output=True, text=True, timeout=15,
            env=env, cwd=str(self.repo),
        )

    def test_tree_writes_bidirectional_map(self):
        r = self._run("tree", "--file", str(self.yaml), "--since", "2020-01-01")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("by_commit", data)
        self.assertIn("by_task", data)
        self.assertIn("skipped_no_files", data)
        self.assertEqual(data["by_task"]["wired feature A"],
                          [self.shas["src/a.py"]])
        self.assertEqual(set(data["skipped_no_files"]),
                          {"wrote docs only", "no files attached"})

    def test_tree_missing_file_fails(self):
        r = self._run("tree", "--file", str(self.tmp / "nope.yaml"))
        self.assertNotEqual(r.returncode, 0)

    def test_tree_default_since_from_handoff_date(self):
        # When --since is omitted, defaults to handoff `date:` field.
        # Normalized — bare YYYY-MM-DD gains `00:00:00` time suffix so
        # git's `--since=` reliably catches same-day commits.
        r = self._run("tree", "--file", str(self.yaml))
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["since"], "2026-05-18T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
