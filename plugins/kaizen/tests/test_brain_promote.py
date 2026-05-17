"""Tests for brain_promote.py — project-memory → brain promotion flow."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import _brain  # noqa: E402
import brain_promote as bp  # noqa: E402


def _write_project_memory_entry(
    pm_dir: Path,
    name: str,
    *,
    type_: str = "world-fact",
    sources_count: int = 1,
    promote: bool = False,
    confidence: float | None = None,
) -> Path:
    """Write a project-memory entry with the specified frontmatter."""
    fm_lines = ["---", f"name: {name}", f"description: desc for {name}",
                f"type: {type_}", f"sources_count: {sources_count}"]
    if confidence is not None:
        fm_lines.append(f"confidence: {confidence}")
    if promote:
        fm_lines.append("promote: true")
    fm_lines.extend(["---", "", f"# {name}", "", "body content"])
    p = pm_dir / f"{_brain.slugify(name)}.md"
    p.write_text("\n".join(fm_lines), encoding="utf-8")
    return p


class TestPromoteBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        # Build a fake project-memory dir at the path
        # _brain.project_memory_root() would compute. We monkey-patch
        # the lookup to point here so the test never touches the real
        # per-user projects directory (KAIZEN_*_PATH-style sandboxing).
        self.pm_root = Path(self._tmp.name) / "pm-root"
        self.pm_root.mkdir()
        self._orig = bp._all_project_memory_roots
        bp._all_project_memory_roots = lambda: [self.pm_root]

    def tearDown(self):
        self._tmp.cleanup()
        bp._all_project_memory_roots = self._orig


class TestPromoteFiltering(TestPromoteBase):
    def test_low_source_count_not_promotable(self):
        _write_project_memory_entry(self.pm_root, "low fact", sources_count=1)
        report = bp.promote(brain_root=self.brain)
        self.assertEqual(report["total_candidates"], 0)

    def test_high_source_count_promotable(self):
        _write_project_memory_entry(self.pm_root, "good fact", sources_count=3)
        report = bp.promote(brain_root=self.brain)
        self.assertEqual(report["total_candidates"], 1)
        c = report["candidates"][0]
        self.assertIn("sources_count=3", c["reason"])

    def test_explicit_promote_flag(self):
        _write_project_memory_entry(
            self.pm_root, "promoted fact",
            sources_count=1, promote=True,
        )
        report = bp.promote(brain_root=self.brain)
        self.assertEqual(report["total_candidates"], 1)
        self.assertIn("explicit-promote-flag", report["candidates"][0]["reason"])

    def test_observation_not_eligible(self):
        # Observations are structurally brain-only; nothing to promote.
        _write_project_memory_entry(
            self.pm_root, "alice", type_="observation", sources_count=3,
        )
        report = bp.promote(brain_root=self.brain)
        self.assertEqual(report["total_candidates"], 0)


class TestPromoteApply(TestPromoteBase):
    def test_apply_moves_to_brain_and_tombstones_source(self):
        src = _write_project_memory_entry(
            self.pm_root, "do the X", sources_count=3,
        )
        report = bp.promote(brain_root=self.brain, apply=True)
        self.assertEqual(report["total_applied"], 1)
        # Brain destination exists with promoted frontmatter
        dest = Path(report["applied"][0]["destination"])
        self.assertTrue(dest.is_file())
        dest_text = dest.read_text()
        self.assertIn("promoted_from:", dest_text)
        self.assertIn(str(src), dest_text)
        # Source is tombstoned
        src_text = src.read_text()
        self.assertIn("promoted_to:", src_text)
        self.assertIn(str(dest), src_text)

    def test_dry_run_does_not_write(self):
        src = _write_project_memory_entry(
            self.pm_root, "dry run fact", sources_count=2,
        )
        before = src.read_text()
        report = bp.promote(brain_root=self.brain, apply=False)
        self.assertEqual(report["total_applied"], 0)
        self.assertEqual(src.read_text(), before)
        self.assertFalse((self.brain / "Notes").exists())

    def test_belief_dest_gets_pref_prefix(self):
        _write_project_memory_entry(
            self.pm_root, "terse output",
            type_="belief", sources_count=2, confidence=0.9,
        )
        report = bp.promote(brain_root=self.brain, apply=True)
        dest = Path(report["applied"][0]["destination"])
        self.assertTrue(dest.name.startswith("pref-"))


class TestPromoteFilterGlob(TestPromoteBase):
    def test_filter_glob_restricts(self):
        _write_project_memory_entry(
            self.pm_root, "feedback foo", sources_count=2,
        )
        _write_project_memory_entry(
            self.pm_root, "project bar", sources_count=2,
        )
        # The two entries land at slugified filenames "feedback-foo.md"
        # and "project-bar.md". Test with glob restricting.
        report = bp.promote(
            brain_root=self.brain,
            filter_glob="feedback-*.md",
        )
        self.assertEqual(report["total_candidates"], 1)
        self.assertIn("feedback", report["candidates"][0]["source"])


if __name__ == "__main__":
    unittest.main()
