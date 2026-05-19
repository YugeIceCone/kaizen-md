"""Tests for brain_evolve.py — duplicates / freshness / persona drift."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
sys.path.insert(0, str(_KZ_DIR / "scripts/brain"))

import brain_evolve as be  # noqa: E402


def _write_note(notes_dir: Path, slug: str, **fm) -> Path:
    """Write a Note with the given frontmatter."""
    notes_dir.mkdir(parents=True, exist_ok=True)
    p = notes_dir / f"{slug}.md"
    fm_lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            fm_lines.append(f"{k}: {v}")
    fm_lines.extend(["---", "", f"# {fm.get('name', slug)}", "", "body"])
    p.write_text("\n".join(fm_lines), encoding="utf-8")
    return p


class TestDuplicateDetection(unittest.TestCase):
    def test_finds_duplicate_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            _write_note(notes, "pref-terse", name="Prefer terse", type="belief", confidence=0.9)
            _write_note(notes, "obs-terse", name="Obs terse", type="observation")
            # Both share root stem "terse" after prefix-strip
            report = be.evolve(brain_root=brain)
            stems = [d["stem"] for d in report["duplicates"]]
            self.assertIn("terse", stems)

    def test_unique_stems_no_dupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            _write_note(notes, "pref-a", name="A", type="belief", confidence=0.9)
            _write_note(notes, "pref-b", name="B", type="belief", confidence=0.9)
            report = be.evolve(brain_root=brain)
            self.assertEqual(report["duplicates"], [])


class TestFreshness(unittest.TestCase):
    def test_no_freshness_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            _write_note(notes, "no-fresh", name="N", type="world-fact")
            report = be.evolve(brain_root=brain)
            recs = [n["recommendation"] for n in report["freshness_drift"]]
            self.assertIn("set-freshness", recs)

    def test_fresh_label_with_old_mtime_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            p = _write_note(
                notes, "old-fresh",
                name="Old fresh", type="belief",
                confidence=0.8, freshness="fresh",
            )
            # Backdate mtime to 60 days ago
            old = time.time() - 60 * 86400
            os.utime(p, (old, old))
            report = be.evolve(brain_root=brain, stale_days=30)
            recs = [n["recommendation"] for n in report["freshness_drift"]]
            self.assertIn("demote-to-stable", recs)

    def test_recent_fresh_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            _write_note(
                notes, "recent-fresh",
                name="Recent fresh", type="belief",
                confidence=0.8, freshness="fresh",
            )
            report = be.evolve(brain_root=brain, stale_days=30)
            paths_flagged = {n["path"] for n in report["freshness_drift"]}
            self.assertNotIn(
                str(notes / "recent-fresh.md"), paths_flagged,
            )


class TestPersonaDrift(unittest.TestCase):
    def test_persona_drift_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            _write_note(
                notes, "pref-x",
                name="Pref X", type="belief",
                confidence=0.9, sources_count=5,
            )
            # Persona references it with conf=0.7 sources=1 (drifted)
            persona = brain / "Persona.md"
            persona.write_text(
                "# Persona\n\n## Top Beliefs\n\n"
                "1. [[Notes/pref-x.md]] — conf=0.70 sources=1 freshness=stable\n",
            )
            report = be.evolve(brain_root=brain)
            issues = [d["issue"] for d in report["persona_drift"]]
            self.assertIn("sources-drift", issues)
            self.assertIn("conf-drift", issues)

    def test_persona_in_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            notes = brain / "Notes"
            _write_note(
                notes, "pref-y",
                name="Pref Y", type="belief",
                confidence=0.85, sources_count=3,
            )
            persona = brain / "Persona.md"
            persona.write_text(
                "# Persona\n\n## Top Beliefs\n\n"
                "1. [[Notes/pref-y.md]] — conf=0.85 sources=3 freshness=stable\n",
            )
            report = be.evolve(brain_root=brain)
            self.assertEqual(report["persona_drift"], [])


class TestEmptyBrain(unittest.TestCase):
    def test_empty_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            brain.mkdir()
            report = be.evolve(brain_root=brain)
            self.assertEqual(report["total_notes"], 0)
            self.assertEqual(report["duplicates"], [])


if __name__ == "__main__":
    unittest.main()
