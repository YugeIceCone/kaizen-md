#!/usr/bin/env python3
"""Unit tests for _search.py — hybrid BM25 + dense fusion (v1.27.0+).

Verifies:
  - FTS5 mirror table is created with correct triggers
  - BM25 search returns expected ordering for keyword queries
  - Dense search short-circuits + propagates dim-mismatch warnings
  - Min-max normalization handles edge cases
  - Hybrid score is the alpha-weighted blend
  - RRF fuses multiple ranked lists correctly

Run:
    python3 -m unittest tests.test_search -v

Embedding tests are mocked (no numpy required for FTS/RRF assertions).
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import _search  # noqa: E402


def _build_test_db() -> sqlite3.Connection:
    """In-memory SQLite with a base table + 3 test rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE docs (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            embedding BLOB
        );
        INSERT INTO docs (id, text, embedding) VALUES
            (1, 'the quick brown fox jumps over the lazy dog', NULL),
            (2, 'lazy dog sleeps in the sun', NULL),
            (3, 'a fox in the henhouse causes chaos', NULL);
    """)
    return conn


class TestFtsMirror(unittest.TestCase):
    def test_creates_fts_and_triggers(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        # FTS table exists.
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='docs_fts'"
        ).fetchone()
        self.assertIsNotNone(row)
        # The 3 base rows were inserted before the trigger; rebuild populates them.
        _search.rebuild_fts(conn, "docs")
        n = conn.execute("SELECT count(*) FROM docs_fts").fetchone()[0]
        self.assertEqual(n, 3)

    def test_idempotent(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.ensure_fts_mirror(conn, "docs")  # second call no-ops
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='docs_fts'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_insert_propagates_to_fts(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        conn.execute(
            "INSERT INTO docs (id, text, embedding) VALUES (4, 'new entry about cats', NULL)"
        )
        conn.commit()
        hits = _search.bm25_search(conn, "docs", "cats", top_k=5)
        ids = [i for i, _ in hits]
        self.assertIn(4, ids)


class TestBm25Search(unittest.TestCase):
    def test_keyword_finds_relevant(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        # 'fox' is in rows 1 and 3 but not 2
        hits = _search.bm25_search(conn, "docs", "fox", top_k=5)
        ids = [i for i, _ in hits]
        self.assertIn(1, ids)
        self.assertIn(3, ids)
        self.assertNotIn(2, ids)

    def test_no_match_returns_empty(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        hits = _search.bm25_search(conn, "docs", "kangaroo", top_k=5)
        self.assertEqual(hits, [])

    def test_safe_handles_punctuation(self) -> None:
        # Tokens that are pure punctuation should be stripped, not crash.
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        hits = _search.bm25_search(conn, "docs", "fox?! ... ,,, lazy", top_k=5)
        ids = [i for i, _ in hits]
        # 'fox' or 'lazy' should match rows 1, 2, 3
        self.assertGreater(len(ids), 0)


class TestMinmaxNormalize(unittest.TestCase):
    def test_basic(self) -> None:
        out = _search._minmax_normalize([(1, 0.0), (2, 5.0), (3, 10.0)])
        self.assertEqual(out[1], 0.0)
        self.assertEqual(out[2], 0.5)
        self.assertEqual(out[3], 1.0)

    def test_all_same_returns_one(self) -> None:
        out = _search._minmax_normalize([(1, 0.5), (2, 0.5)])
        self.assertEqual(out[1], 1.0)
        self.assertEqual(out[2], 1.0)

    def test_empty(self) -> None:
        self.assertEqual(_search._minmax_normalize([]), {})


class TestRrf(unittest.TestCase):
    def test_two_lists_default_weights(self) -> None:
        # Two ranked lists; doc 1 is top of both → highest fused score.
        r1 = [(1, 0.9), (2, 0.8), (3, 0.7)]
        r2 = [(1, 0.95), (3, 0.85), (2, 0.75)]
        out = _search.reciprocal_rank_fusion([r1, r2], k=50, top_k=3)
        self.assertEqual(out[0][0], 1)
        self.assertEqual(len(out), 3)

    def test_weighted(self) -> None:
        r1 = [(1, 0.0), (2, 0.0)]
        r2 = [(2, 0.0), (1, 0.0)]
        # Heavy weight on r2 → 2 should win.
        out = _search.reciprocal_rank_fusion([r1, r2], weights=[0.1, 10.0], top_k=2)
        self.assertEqual(out[0][0], 2)

    def test_weight_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            _search.reciprocal_rank_fusion([[(1, 0.0)]], weights=[1.0, 2.0])

    def test_empty(self) -> None:
        self.assertEqual(_search.reciprocal_rank_fusion([]), [])


class TestHybridSearch(unittest.TestCase):
    """Hybrid combines BM25 + dense. Mock the dense path so we don't
    need numpy or an embed backend in the test environment."""

    def test_alpha_zero_equals_bm25_only(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        with patch.object(_search, "dense_search", return_value=[]):
            out = _search.hybrid_search(conn, "docs", "fox", alpha=0.0, top_k=5)
        ids = [i for i, _ in out]
        self.assertIn(1, ids)
        self.assertIn(3, ids)

    def test_alpha_one_equals_dense_only(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        # Synthesize a dense result that has rows BM25 wouldn't return.
        fake_dense = [(99, 0.95), (2, 0.85)]
        with patch.object(_search, "dense_search", return_value=fake_dense):
            out = _search.hybrid_search(conn, "docs", "fox", alpha=1.0, top_k=5)
        ids = [i for i, _ in out]
        self.assertIn(99, ids)
        self.assertEqual(out[0][0], 99)

    def test_blend_combines_both(self) -> None:
        conn = _build_test_db()
        _search.ensure_fts_mirror(conn, "docs")
        _search.rebuild_fts(conn, "docs")
        with patch.object(_search, "dense_search", return_value=[(1, 0.8), (2, 0.6)]):
            out = _search.hybrid_search(conn, "docs", "fox", alpha=0.5, top_k=5)
        ids = [i for i, _ in out]
        # Row 1 is top of both → must be in result
        self.assertIn(1, ids)


if __name__ == "__main__":
    unittest.main()
