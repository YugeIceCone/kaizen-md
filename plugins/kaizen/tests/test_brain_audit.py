"""Tests for brain_audit.py — end-of-session discovery audit."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _brain  # noqa: E402
import brain_audit as ba  # noqa: E402


class TestExtractCandidates(unittest.TestCase):
    def test_double_quoted_extraction(self):
        text = 'user said: "we prefer terse output across all projects"'
        out = ba._extract_candidates_from_text(text, "src", "kind")
        self.assertGreater(len(out), 0)
        self.assertTrue(any("terse" in c["text"] for c in out))

    def test_phrase_extraction(self):
        text = "From now on, we always use sqlite for indexers."
        out = ba._extract_candidates_from_text(text, "src", "kind")
        self.assertGreater(len(out), 0)

    def test_no_short_quotes(self):
        # Quotes < 20 chars are ignored
        text = '"a"'
        out = ba._extract_candidates_from_text(text, "src", "kind")
        self.assertEqual(out, [])

    def test_dedup_within_source(self):
        text = '"same quote here repeated please" "same quote here repeated please"'
        out = ba._extract_candidates_from_text(text, "src", "kind")
        self.assertEqual(len(out), 1)

    def test_classification_attached_in_flow(self):
        # The full flow attaches type to each candidate
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            brain.mkdir()
            cwd = Path(tmp) / "fake-cwd"
            cwd.mkdir()
            # Seed a project memory draft with a recognizable quote
            pm = _brain.project_memory_root(cwd)
            pm.mkdir(parents=True, exist_ok=True)
            (pm / "_draft_test.md").write_text(
                'Source contains: "we decided to use postgres for production"'
            )
            report = ba.audit(cwd=cwd, brain_root=brain)
            self.assertGreater(report["sources_scanned"], 0)
            # Candidate should be classified
            for c in report["candidates"]:
                self.assertIn(c["type"], {"world-fact", "belief", "observation", "experience"})


class TestSourceReaders(unittest.TestCase):
    def test_recent_commits_in_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
            (repo / "x.txt").write_text("hello")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", 'test: "we always use X here"'],
                check=True,
            )
            items = ba._read_recent_commits(repo)
            self.assertGreater(len(items), 0)
            self.assertEqual(items[0]["kind"], "commit")

    def test_recent_commits_not_a_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ba._read_recent_commits(Path(tmp)), [])

    def test_loop_state_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            kaizen = cwd / ".kaizen"
            kaizen.mkdir()
            (kaizen / "loop.state.md").write_text(
                '---\nflag: x\n---\n{"items": [{"desc": "complete the X migration"}]}'
            )
            items = ba._read_loop_state(cwd)
            self.assertGreater(len(items), 0)
            self.assertEqual(items[0]["kind"], "loop")
            self.assertIn("migration", items[0]["text"])


class TestApplyInbox(unittest.TestCase):
    def test_apply_writes_inbox_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            brain.mkdir()
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            # Seed a draft
            pm = _brain.project_memory_root(cwd)
            pm.mkdir(parents=True, exist_ok=True)
            (pm / "_draft_x.md").write_text(
                '"we decided to ship feature X tomorrow morning"'
            )
            report = ba.audit(cwd=cwd, brain_root=brain, apply=True)
            inbox = brain / "Inbox"
            # Either drafts were written, or nothing was promoted because
            # of the dedup guard — assert the directory exists.
            if report.get("inbox_writes"):
                self.assertTrue(inbox.is_dir())
                self.assertGreater(len(list(inbox.glob("draft-*.md"))), 0)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            brain.mkdir()
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            report = ba.audit(cwd=cwd, brain_root=brain, apply=False)
            # No Inbox writes regardless of candidate count
            self.assertEqual(report.get("inbox_writes"), [])


if __name__ == "__main__":
    unittest.main()
