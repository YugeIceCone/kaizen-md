"""Tests for handoff.py::scaffold commit auto-tagging into done_this_session.

The scaffold previously produced `done_this_session: - task: TBD\n    files: [...]`
but left the per-task `commits:` field empty — agents had to hand-type the SHAs at
end-of-session (see prior session's handoff at ~/.claude/handoff/kaizen-md/
2026-05-18_17-29_built-parallel-branches-kit-spec-11-docs.yaml lines 124-156).

This wiring attaches `commits: [<short-sha>, ...]` automatically via
_auto_tag_commits(repo, files, since=...) which was defined but unused
(handoff.py:687-710 at the time of this change). Per-entry attribution:

- umbrella fallback (no JSONL completed-tasks): single TBD entry gets ALL
  commits in the window.
- completed-task entries (from JSONL mining): each gets a subject-substring
  heuristic match against commit messages; trailing synthetic entry gets
  ALL commits as a catch-all so nothing is lost.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "scripts/handoff"
_HANDOFF_PY = _SCRIPTS / "handoff.py"

sys.path.insert(0, str(_SCRIPTS))
import handoff  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15)


class _RepoBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.handoffs_dir = self.tmp / "handoffs"
        self.handoffs_dir.mkdir()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for cmd in (
            ["git", "init", "-q", "-b", "master"],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
        ):
            subprocess.run(cmd, cwd=str(self.repo), check=True, capture_output=True)
        self._orig_dir = os.environ.get("KAIZEN_HANDOFF_DIR")
        self._orig_db = os.environ.get("KAIZEN_HANDOFF_DB")
        os.environ["KAIZEN_HANDOFF_DIR"] = str(self.handoffs_dir)
        os.environ["KAIZEN_HANDOFF_DB"] = str(self.tmp / "handoff.db")

    def tearDown(self):
        self._tmp.cleanup()
        for var, orig in (("KAIZEN_HANDOFF_DIR", self._orig_dir),
                          ("KAIZEN_HANDOFF_DB", self._orig_db)):
            if orig is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = orig

    def _commit(self, rel: str, content: str, msg: str | None = None) -> str:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        _git(self.repo, "add", rel)
        _git(self.repo, "commit", "-q", "-m", msg or f"add {rel}")
        return _git(self.repo, "rev-parse", "--short", "HEAD").stdout.strip()


class TestAutoTagHelper(_RepoBase):
    """Direct unit tests for _auto_tag_commits — confirm signature/contract."""

    def test_empty_files_returns_empty(self):
        self.assertEqual(handoff._auto_tag_commits(self.repo, [], since="1970-01-01"), [])

    def test_returns_commits_chronological(self):
        sha1 = self._commit("a.py", "1\n")
        sha2 = self._commit("a.py", "2\n")
        sha3 = self._commit("b.py", "x\n")
        out = handoff._auto_tag_commits(self.repo, ["a.py"], since="1970-01-01")
        self.assertEqual(out, [sha1, sha2])
        self.assertNotIn(sha3, out)


class TestScaffoldUmbrellaCommits(_RepoBase):
    """Umbrella fallback path (no JSONL mining): all-window commits attached."""

    def test_umbrella_entry_includes_commits(self):
        sha1 = self._commit("a.py", "1\n")
        sha2 = self._commit("b.py", "2\n")
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "scaffold",
             "--session", "demo",
             "--goal", "did the thing",
             "--now", "do the next thing",
             "--at", "2026-05-17_03-00",
             "--no-session-mine",
             "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.repo),
            env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        yaml_path = Path(env["data"]["yaml_path"])
        body = yaml_path.read_text(encoding="utf-8")
        # The umbrella entry MUST carry both SHAs.
        self.assertIn("done_this_session:", body)
        self.assertIn(f"commits: [{sha1}, {sha2}]", body)


class TestQuoteIfUnsafeColonRegression(_RepoBase):
    """Ensure the test_handoff_scaffold's quote-if-unsafe behavior is preserved
    (the auto-tag rendering MUST NOT break YAML by emitting unquoted colon-
    containing values).
    """

    def test_render_safe_with_a_colon_containing_commit_msg(self):
        # Commit subject deliberately contains ": " — auto-tag MUST still produce
        # valid YAML (the rendered commits: line is a YAML flow sequence of bare
        # short SHAs, no commit subjects, so this should pass trivially).
        sha = self._commit("x.py", "1\n", msg="chore(scope): contains: colon")
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "scaffold",
             "--session", "demo",
             "--goal", "ok",
             "--now", "ok",
             "--at", "2026-05-17_03-00",
             "--no-session-mine",
             "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.repo),
            env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        body = Path(env["data"]["yaml_path"]).read_text(encoding="utf-8")
        # Must be parsable as YAML — short-SHA-only flow seq is bullet-proof.
        import yaml as _yaml
        # Strip frontmatter; parse body
        if body.startswith("---"):
            _, _, body_only = body.split("---", 2)
        else:
            body_only = body
        parsed = _yaml.safe_load(body_only)
        self.assertIn("done_this_session", parsed)
        self.assertEqual(len(parsed["done_this_session"]), 1)
        # Stringify to handle YAML's int-coercion of all-digit short SHAs
        # (~5% of random 7-hex-char SHAs are all-decimal → parsed as int).
        rendered = [str(c) for c in parsed["done_this_session"][0]["commits"]]
        self.assertIn(sha, rendered)


class TestScaffoldJSONLMinedCommits(_RepoBase):
    """Covers the JSONL-mined completed_tasks branch (the other half of the
    feature — not exercised by TestScaffoldUmbrellaCommits which passes
    --no-session-mine). Per-task entries MUST get `commits: []` placeholder;
    the synthetic trailing entry MUST carry ALL window SHAs as a catch-all
    so agents can re-distribute manually.
    """

    def setUp(self):
        super().setUp()
        # Sandbox HOME so cwd_to_slug points into our tempdir's fake CC tree.
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()
        slug = str(self.repo.resolve()).replace("/", "-")
        self.fake_proj = self.fake_home / ".claude" / "projects" / slug
        self.fake_proj.mkdir(parents=True)
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.fake_home)

    def tearDown(self):
        if self._orig_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._orig_home
        super().tearDown()

    def _seed_jsonl_with_completed_task(self) -> None:
        records = [
            {"type": "user", "timestamp": "2026-05-17T03:00:00.000Z",
              "message": {"role": "user",
                           "content": [{"type": "text", "text": "go"}]}},
            {"type": "assistant", "timestamp": "2026-05-17T03:00:05.000Z",
              "message": {"role": "assistant", "content": [
                  {"type": "tool_use", "id": "tu1", "name": "TaskCreate",
                    "input": {"subject": "first task subject",
                                "description": "..."}}]}},
            {"type": "user", "timestamp": "2026-05-17T03:00:06.000Z",
              "message": {"role": "user", "content": [
                  {"type": "tool_result", "tool_use_id": "tu1",
                    "content": "Task #1 created successfully: first task subject"}]}},
            {"type": "assistant", "timestamp": "2026-05-17T03:00:10.000Z",
              "message": {"role": "assistant", "content": [
                  {"type": "tool_use", "id": "tu2", "name": "TaskUpdate",
                    "input": {"taskId": "1", "status": "completed"}}]}},
        ]
        p = self.fake_proj / "sess-test.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_per_task_entries_get_empty_commits_placeholder(self):
        sha1 = self._commit("a.py", "1\n")
        sha2 = self._commit("b.py", "2\n")
        self._seed_jsonl_with_completed_task()
        r = subprocess.run(
            [sys.executable, str(_HANDOFF_PY), "scaffold",
             "--session", "demo",
             "--goal", "g",
             "--now",  "n",
             "--at",   "2026-05-17_03-00",
             "--since", "2000-01-01",   # window covers all session commits
             "--json"],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.repo),
            env=os.environ.copy(),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        body = Path(json.loads(r.stdout)["data"]["yaml_path"]).read_text(
            encoding="utf-8"
        )
        # Per-task entry has commits: [] placeholder
        self.assertIn("- task: first task subject", body)
        self.assertIn("    commits: []", body)
        self.assertIn("    files: []", body)
        # Synthetic trailing entry exists AND carries ALL window SHAs
        self.assertIn("- task: (git-touched files this session)", body)
        self.assertIn(f"    commits: [{sha1}, {sha2}]", body)


if __name__ == "__main__":
    unittest.main()
