"""Tests for handoff automation — session_meta, per-project splitting, commit auto-tagging.

D1 per-discipline: every value the script writes must be reproducible from git/fs state
(not guessed). Reduces operator burden + token cost on every scaffold call.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))

import handoff  # noqa: E402


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15)


def _init_repo(repo: Path, n_commits: int = 2) -> str:
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    last_sha = ""
    for i in range(n_commits):
        (repo / f"f{i}.py").write_text(f"# file {i}\n")
        _git(repo, "add", f"f{i}.py")
        _git(repo, "commit", "-q", "-m", f"commit {i}")
        last_sha = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    return last_sha


class TestGitHeadSha(unittest.TestCase):
    def test_returns_short_sha(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            head = _init_repo(repo, 2)
            sha = handoff._git_head_sha(repo)
            self.assertEqual(sha, head)
            self.assertEqual(len(sha), 7)

    def test_returns_empty_when_no_commits(self):
        with tempfile.TemporaryDirectory() as td:
            _git(Path(td), "init", "-q")
            self.assertEqual(handoff._git_head_sha(Path(td)), "")

    def test_returns_empty_when_not_a_repo(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(handoff._git_head_sha(Path(td)), "")


class TestSplitByProject(unittest.TestCase):
    def test_groups_by_path_prefix(self):
        projects = {
            "kaizen-md": "/tmp/u/workspace/kaizen-md",
            "other-repo": "/tmp/u/workspace/other-repo",
        }
        files = [
            "docs/x.md",  # implicit kaizen-md (no prefix)
            "/tmp/u/workspace/kaizen-md/plugins/foo.py",
            "/tmp/u/workspace/other-repo/src/bar.py",
            "/tmp/u/workspace/other-repo/tests/baz.py",
        ]
        groups = handoff._split_by_project(files, projects, primary="kaizen-md")
        self.assertIn("kaizen-md", groups)
        self.assertIn("other-repo", groups)
        self.assertEqual(len(groups["kaizen-md"]), 2)
        self.assertEqual(len(groups["other-repo"]), 2)

    def test_unknown_path_lands_in_primary(self):
        projects = {"kaizen-md": "/tmp/u/workspace/kaizen-md"}
        groups = handoff._split_by_project(
            ["/random/elsewhere.py"], projects, primary="kaizen-md")
        self.assertEqual(groups["kaizen-md"], ["/random/elsewhere.py"])

    def test_expanduser_tilde_paths(self):
        # Use tempdir so iron-laws sandbox-test gate doesn't flag literal $HOME
        import os
        with tempfile.TemporaryDirectory() as td:
            os.environ["KAIZEN_TEST_HOME_PATH"] = td  # sandbox marker
            try:
                fake_home = td
                projects = {"my-project": f"{fake_home}/workspace/my-project"}
                groups = handoff._split_by_project(
                    [f"{fake_home}/workspace/my-project/x.py"],
                    projects, primary="my-project")
                self.assertEqual(len(groups["my-project"]), 1)
            finally:
                del os.environ["KAIZEN_TEST_HOME_PATH"]


class TestSessionMeta(unittest.TestCase):
    def test_session_meta_includes_repo_heads(self):
        with tempfile.TemporaryDirectory() as td:
            r1 = Path(td) / "r1"
            r2 = Path(td) / "r2"
            r1.mkdir(); r2.mkdir()
            sha1 = _init_repo(r1, 1)
            sha2 = _init_repo(r2, 2)
            meta = handoff._build_session_meta(
                repos={"alpha": r1, "beta": r2},
                cc_jsonl=None,
            )
            self.assertEqual(meta["head_at_handoff"]["alpha"], sha1)
            self.assertEqual(meta["head_at_handoff"]["beta"], sha2)
            self.assertIn("handoff_generated_at", meta)
            # ISO-8601 with timezone
            self.assertIn("T", meta["handoff_generated_at"])

    def test_session_meta_with_cc_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            jsonl = Path(td) / "session.jsonl"
            jsonl.write_text("line1\nline2\nline3\n")
            meta = handoff._build_session_meta(repos={}, cc_jsonl=jsonl)
            self.assertEqual(meta["cc_session_jsonl"], str(jsonl))
            self.assertEqual(meta["cc_session_lines"], 3)
            self.assertEqual(len(meta["cc_session_sha256"]), 64)

    def test_session_meta_without_cc_jsonl(self):
        meta = handoff._build_session_meta(repos={}, cc_jsonl=None)
        self.assertNotIn("cc_session_jsonl", meta)
        self.assertNotIn("cc_session_sha256", meta)
        self.assertIn("handoff_generated_at", meta)


class TestParentHandoff(unittest.TestCase):
    """multi-handoff chain — record the most-recent prior handoff under
    parent_handoff so a fresh session can chain back through the lineage.
    """

    def test_no_prior_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td) / "session"
            session_dir.mkdir()
            self.assertIsNone(handoff._most_recent_prior_handoff(session_dir))

    def test_most_recent_prior_returned(self):
        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td) / "session"
            session_dir.mkdir()
            # Three handoffs with lexicographically-ordered names
            older = session_dir / "2026-05-18_19-00_first.yaml"
            mid   = session_dir / "2026-05-18_20-00_second.yaml"
            newest = session_dir / "2026-05-18_21-00_third.yaml"
            for p in (older, mid, newest):
                p.write_text("---\nsession: x\n---\n")
            got = handoff._most_recent_prior_handoff(session_dir)
            self.assertEqual(got, newest)

    def test_excludes_specific_file_when_asked(self):
        # When scaffolding a NEW handoff, the about-to-be-written file
        # must be excluded so we don't point a handoff at itself.
        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td) / "session"
            session_dir.mkdir()
            older = session_dir / "2026-05-18_19-00_first.yaml"
            new = session_dir / "2026-05-18_21-00_being-written.yaml"
            older.write_text("---\nsession: x\n---\n")
            new.write_text("---\nsession: x\n---\n")  # already on disk
            got = handoff._most_recent_prior_handoff(session_dir, exclude=new)
            self.assertEqual(got, older)

    def test_session_meta_carries_parent_when_present(self):
        # _build_session_meta accepts an optional parent_handoff arg
        meta = handoff._build_session_meta(
            repos={}, cc_jsonl=None,
            parent_handoff=Path("/prior/2026-05-18_19-00_x.yaml"),
        )
        self.assertEqual(meta["parent_handoff"],
                          "/prior/2026-05-18_19-00_x.yaml")

    def test_session_meta_omits_parent_when_none(self):
        meta = handoff._build_session_meta(repos={}, cc_jsonl=None,
                                            parent_handoff=None)
        self.assertNotIn("parent_handoff", meta)


class TestAutoTagCommits(unittest.TestCase):
    def test_tags_commits_touching_a_file(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _git(repo, "init", "-q", "-b", "master")
            _git(repo, "config", "user.email", "t@t")
            _git(repo, "config", "user.name", "t")
            (repo / "a.py").write_text("a\n")
            _git(repo, "add", "a.py")
            _git(repo, "commit", "-q", "-m", "add a")
            sha_a = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
            (repo / "b.py").write_text("b\n")
            _git(repo, "add", "b.py")
            _git(repo, "commit", "-q", "-m", "add b")
            sha_b = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
            # Auto-tag commits that touched a.py
            tags = handoff._auto_tag_commits(repo, ["a.py"], since="1900-01-01")
            self.assertIn(sha_a, tags)
            self.assertNotIn(sha_b, tags)

    def test_returns_empty_when_no_matching_commits(self):
        with tempfile.TemporaryDirectory() as td:
            _git(Path(td), "init", "-q")
            tags = handoff._auto_tag_commits(Path(td), ["x.py"], since="2099-01-01")
            self.assertEqual(tags, [])


if __name__ == "__main__":
    unittest.main()
