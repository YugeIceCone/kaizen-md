"""Tests for build_index.py — SQLite + sentence-transformers index
over the Second Brain.

Most tests run with KAIZEN_BRAIN_INDEX_SKIP_EMBED=1 to avoid loading
the embedding model (heavy / not always installed). The fallback
LIKE search path is what gets exercised.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))

import build_index as bi  # noqa: E402


def _seed_brain(root: Path):
    """Create a minimal brain tree with one Note per type."""
    (root / "Notes").mkdir(parents=True)
    (root / "Projects" / "proj-a").mkdir(parents=True)
    (root / "People").mkdir(parents=True)

    (root / "Notes" / "pref-terse.md").write_text(
        "---\nname: Prefer terse output\n"
        "description: User wants short answers without padding\n"
        "type: belief\nconfidence: 0.9\n"
        "tags: [preference, communication]\n"
        "sources_count: 3\nfreshness: stable\n"
        "---\n\n"
        "# Prefer terse output\n\n"
        "Long-form responses get trimmed.\n"
    )
    (root / "Notes" / "decision-sqlite.md").write_text(
        "---\nname: We use SQLite over Postgres for local indexes\n"
        "description: SQLite ships everywhere; Postgres needs a daemon\n"
        "type: world-fact\nsources_count: 2\n"
        "tags: [decisions, infrastructure]\n"
        "---\n\n"
        "We chose SQLite for all kaizen indexers.\n"
    )
    (root / "People" / "alice.md").write_text(
        "---\nname: Alice\n"
        "description: Backend lead; deep async expertise\n"
        "type: observation\n---\n\n"
        "Worked with Alice on the rewrite.\n"
    )
    (root / "Projects" / "proj-a" / "proj-a.md").write_text(
        "---\nname: Project A\n"
        "description: Internal data pipeline\n"
        "type: observation\n---\n\n"
        "Project A pipeline notes.\n"
    )


class BrainIndexBase(unittest.TestCase):
    """Base class — sandbox the brain root + db path for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.brain.mkdir()
        _seed_brain(self.brain)
        self._orig_db = os.environ.get("KAIZEN_BRAIN_DB")
        self._orig_brain = os.environ.get("KAIZEN_BRAIN_DIR")
        os.environ["KAIZEN_BRAIN_DB"] = str(Path(self._tmp.name) / "brain.db")
        os.environ["KAIZEN_BRAIN_DIR"] = str(self.brain)
        os.environ["KAIZEN_BRAIN_INDEX_SKIP_EMBED"] = "1"

    def tearDown(self):
        self._tmp.cleanup()
        for k, v in (
            ("KAIZEN_BRAIN_DB", self._orig_db),
            ("KAIZEN_BRAIN_DIR", self._orig_brain),
            ("KAIZEN_BRAIN_INDEX_SKIP_EMBED", None),
        ):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestIndexBuild(BrainIndexBase):
    def test_index_populates_table(self):
        report = bi.do_index(brain_root=self.brain)
        self.assertGreaterEqual(report["discovered"], 4)
        self.assertGreaterEqual(report["inserted"], 4)
        # Re-index — nothing new
        report2 = bi.do_index(brain_root=self.brain)
        self.assertEqual(report2["inserted"], 0)
        self.assertEqual(report2["updated"], 0)

    def test_incremental_update_on_change(self):
        bi.do_index(brain_root=self.brain)
        # Change one note
        p = self.brain / "Notes" / "pref-terse.md"
        text = p.read_text().replace(
            "sources_count: 3", "sources_count: 4"
        )
        p.write_text(text)
        report = bi.do_index(brain_root=self.brain)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(report["inserted"], 0)

    def test_stale_cleanup(self):
        bi.do_index(brain_root=self.brain)
        # Remove a file; re-index should drop it
        (self.brain / "Notes" / "pref-terse.md").unlink()
        report = bi.do_index(brain_root=self.brain)
        self.assertGreaterEqual(report["removed"], 1)


class TestSearch(BrainIndexBase):
    def setUp(self):
        super().setUp()
        bi.do_index(brain_root=self.brain)

    def test_text_search_finds_belief(self):
        results = bi.do_search("terse")
        self.assertGreater(len(results), 0)
        names = [r["name"] for r in results]
        self.assertTrue(any("terse" in n.lower() for n in names))

    def test_filter_by_type(self):
        results = bi.do_search(
            "user", type_filter="belief",
        )
        for r in results:
            self.assertEqual(r["type"], "belief")

    def test_filter_by_subdir(self):
        results = bi.do_search("project", subdir_filter="Projects")
        for r in results:
            self.assertEqual(r["subdir"], "Projects")

    def test_min_confidence_filter(self):
        results = bi.do_search("output", min_confidence=0.85)
        for r in results:
            self.assertIsNotNone(r["confidence"])
            self.assertGreaterEqual(r["confidence"], 0.85)


class TestStats(BrainIndexBase):
    def test_stats_after_index(self):
        bi.do_index(brain_root=self.brain)
        stats = bi.do_stats()
        self.assertGreaterEqual(stats["total"], 4)
        self.assertIn("belief", stats["by_type"])
        self.assertIn("observation", stats["by_type"])
        self.assertIn("Notes", stats["by_subdir"])
        self.assertIn("People", stats["by_subdir"])
        self.assertTrue(stats["last_indexed_ts"])


class TestGet(BrainIndexBase):
    def test_get_by_id(self):
        bi.do_index(brain_root=self.brain)
        # Find an id via search
        results = bi.do_search("terse")
        self.assertGreater(len(results), 0)
        item = bi.do_get(results[0]["id"])
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], results[0]["id"])

    def test_get_missing_returns_none(self):
        bi.do_index(brain_root=self.brain)
        self.assertIsNone(bi.do_get(99999))


class TestClear(BrainIndexBase):
    def test_clear_removes_db(self):
        bi.do_index(brain_root=self.brain)
        out = bi.do_clear()
        self.assertTrue(out["cleared"])
        # Re-running on missing file returns cleared=False
        out2 = bi.do_clear()
        self.assertFalse(out2["cleared"])


class TestPath(unittest.TestCase):
    def test_env_db_wins(self):
        orig = os.environ.get("KAIZEN_BRAIN_DB")
        os.environ["KAIZEN_BRAIN_DB"] = "/tmp/x.db"
        try:
            self.assertEqual(str(bi.db_path()), "/tmp/x.db")
        finally:
            if orig is None:
                del os.environ["KAIZEN_BRAIN_DB"]
            else:
                os.environ["KAIZEN_BRAIN_DB"] = orig


class TestCli(BrainIndexBase):
    def test_index_then_stats_cli(self):
        import subprocess
        script = _KZ_DIR / "skills/workflow/scripts/build_index.py"
        env = os.environ.copy()
        r1 = subprocess.run(
            ["python3", str(script), "index"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(r1.returncode, 0)
        r2 = subprocess.run(
            ["python3", str(script), "stats"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(r2.returncode, 0)
        out = json.loads(r2.stdout)
        self.assertGreater(out["total"], 0)


if __name__ == "__main__":
    unittest.main()
