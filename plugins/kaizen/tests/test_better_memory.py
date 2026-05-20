"""Tests for kaizen-memory — auto-memory MEMORY.md index management.

The auto-memory dir (~/.claude/projects/<slug>/memory/) accumulates
project_*.md + feedback_*.md captures over time. MEMORY.md is the
index Claude Code auto-loads at session start (first 200 lines /
25KB). kaizen-memory keeps MEMORY.md in sync with the captured files.
"""
import os
import sys
import unittest
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
class TestRegenIndex(unittest.TestCase):
    """`memory.regen_index(dir)` rebuilds MEMORY.md from the
    name + description frontmatter of every *.md sibling."""

    def _seed(self, root: Path, name: str, body: str) -> None:
        (root / name).write_text(body)

    def test_empty_dir_writes_minimal_index(self):
        import better_memory as mc
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            n = mc.regen_index(d)
            self.assertEqual(n, 0)
            self.assertTrue((d / "MEMORY.md").is_file())

    def test_indexes_well_formed_entries(self):
        import better_memory as mc
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._seed(d, "project_x.md",
                "---\nname: Project X\ndescription: Decided to ship feature X\ntype: world-fact\n---\n")
            self._seed(d, "feedback_y.md",
                "---\nname: User prefers terse output\ndescription: Drop trailing summaries\ntype: feedback\n---\n")
            n = mc.regen_index(d)
            text = (d / "MEMORY.md").read_text()
            self.assertEqual(n, 2)
            self.assertIn("Project X", text)
            self.assertIn("Decided to ship feature X", text)
            self.assertIn("User prefers terse output", text)
            self.assertIn("## Feedback", text)
            self.assertIn("## Project", text)

    def test_skips_existing_memory_md(self):
        import better_memory as mc
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._seed(d, "MEMORY.md", "old index\n")
            self._seed(d, "project_a.md",
                "---\nname: A\ndescription: A entry\n---\n")
            mc.regen_index(d)
            text = (d / "MEMORY.md").read_text()
            self.assertNotIn("](MEMORY.md)", text)
            self.assertIn("](project_a.md)", text)

    def test_normalizes_broken_yaml_frontmatter(self):
        """Broken double-quoted strings + escape leakage from prior
        auto-capture must produce a usable index entry (not crash)."""
        import better_memory as mc
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self._seed(d, "project_broken.md",
                '---\nname: "broken string never closes\n'
                'description: "trailing dash — and \\u2014 escape\n'
                'type: world-fact\n---\n')
            n = mc.regen_index(d)
            text = (d / "MEMORY.md").read_text()
            self.assertEqual(n, 1)
            # Em-dash should render correctly (not mojibake)
            self.assertIn("—", text)
            self.assertIn("](project_broken.md)", text)

class TestDefaultMemoryDir(unittest.TestCase):
    """`_default_memory_dir()` resolves to the git repo root's slug per
    Claude Code's convention — all worktrees + subdirs of a repo share
    one auto-memory directory.

    Sandbox via ``KAIZEN_BETTER_MEMORY_DIR`` env override (per the
    kaizen per-feature env convention). Tests never touch real
    ~/.claude — fully mocked.
    """

    def test_env_override_wins(self):
        """KAIZEN_BETTER_MEMORY_DIR env beats git-root resolution."""
        from unittest.mock import patch
        import better_memory as mc

        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"KAIZEN_BETTER_MEMORY_DIR": td}):
                d = mc._default_memory_dir()
            self.assertEqual(str(d), td)

    def test_uses_git_repo_root_when_in_repo(self):
        """Sandboxed: subprocess.run + Path.home mocked, never touches
        real ~/.claude or real git."""
        from unittest.mock import patch
        import better_memory as mc

        fake_repo = "/fake/repo/root"

        def fake_run(*args, **kw):
            class R:
                returncode = 0
                stdout = fake_repo + "\n"
                stderr = ""
            return R()

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(mc.Path, "home", return_value=Path("/fake/home")):
            d = mc._default_memory_dir()

        self.assertIn(fake_repo.replace("/", "-"), str(d))
        self.assertTrue(str(d).endswith("/memory"))
        self.assertTrue(str(d).startswith("/fake/home/.claude/projects/"))

    def test_falls_back_to_cwd_outside_git_repo(self):
        """Sandboxed: rc!=0 from git → cwd fallback; home patched."""
        from unittest.mock import patch
        import better_memory as mc

        def fake_run(*args, **kw):
            class R:
                returncode = 128
                stdout = ""
                stderr = "fatal: not a git repository"
            return R()

        fake_cwd = Path("/fake/cwd/outside")
        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(mc.Path, "cwd", return_value=fake_cwd), \
             patch.object(mc.Path, "home", return_value=Path("/fake/home")):
            d = mc._default_memory_dir()

        self.assertIn(str(fake_cwd).replace("/", "-"), str(d))
        self.assertTrue(str(d).startswith("/fake/home/.claude/projects/"))

if __name__ == "__main__":
    unittest.main()
