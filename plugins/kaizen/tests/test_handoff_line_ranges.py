"""Tests for handoff.py line-range capture — D1 explicit-info, fine-grained code context.

Adds: _git_changed_line_ranges(repo, since) → dict[path, list[(start, end)]]
parsed from `git log -U0 -p --pretty=format:` hunk headers (`@@ -A,B +C,D @@`).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "scripts/handoff"))
sys.path.insert(0, str(_KZ / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ / "scripts/rules"))

import handoff  # noqa: E402


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=15)


def _init_repo_with_commits(repo: Path):
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("line1\nline2\nline3\nline4\nline5\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "init")
    # Modify lines 2-3
    (repo / "a.py").write_text("line1\nLINE2-MOD\nLINE3-MOD\nline4\nline5\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "modify-2-3")
    # Add new file
    (repo / "b.py").write_text("new1\nnew2\nnew3\n")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-q", "-m", "add-b")


class TestLineRanges(unittest.TestCase):
    def test_parse_hunk_header_simple(self):
        h = handoff._parse_hunk_header("@@ -10,3 +12,5 @@")
        self.assertEqual(h, (12, 16))  # +12, len 5 → 12..16

    def test_parse_hunk_header_single_line(self):
        h = handoff._parse_hunk_header("@@ -10 +12 @@")
        self.assertEqual(h, (12, 12))  # default length 1

    def test_parse_hunk_header_zero_length(self):
        h = handoff._parse_hunk_header("@@ -10,3 +12,0 @@")
        self.assertIsNone(h)  # length 0 — deletion only

    def test_parse_hunk_header_malformed(self):
        self.assertIsNone(handoff._parse_hunk_header("not a hunk"))
        self.assertIsNone(handoff._parse_hunk_header("@@ broken @@"))

    def test_git_changed_line_ranges_captures_modify(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _init_repo_with_commits(repo)
            ranges = handoff._git_changed_line_ranges(repo, since="1900-01-01")
            self.assertIn("a.py", ranges)
            # 2-3 modify → (2, 3) or similar; b.py creation → (1, 3)
            a_ranges = ranges["a.py"]
            self.assertTrue(any(start <= 2 and end >= 3 for start, end in a_ranges),
                              f"expected (2, 3)-ish in a.py ranges: {a_ranges}")
            self.assertIn("b.py", ranges)
            b_ranges = ranges["b.py"]
            self.assertTrue(any(start == 1 for start, _ in b_ranges))

    def test_git_changed_line_ranges_handles_no_commits(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "t@t")
            _git(repo, "config", "user.name", "t")
            ranges = handoff._git_changed_line_ranges(repo, since="2099-01-01")
            self.assertEqual(ranges, {})


if __name__ == "__main__":
    unittest.main()
