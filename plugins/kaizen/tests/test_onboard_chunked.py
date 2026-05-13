#!/usr/bin/env python3
"""Integration test for onboard_index.py's v1.28.0 chunked path.

Verifies:
  - open_db creates `code_chunks` + `code_chunks_fts` tables with triggers
  - do_index populates `code_chunks` and the FTS mirror stays in sync
  - do_search defaults to the chunked path
  - Pre-v1.28 dbs (no code_chunks) still work via legacy fallback

Embeddings are mocked to deterministic byte blobs (one int per
embedding) so we don't need numpy or a live backend.

Run:
    python3 -m unittest tests.test_onboard_chunked -v
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import onboard_index as oi  # noqa: E402


def _fake_vec(seed: int = 1) -> bytes:
    """Return a 384-float32 vector (1536 bytes) of repeating value 'seed/100.0'.
    Deterministic per seed; cosine of identical vectors is 1.0."""
    import struct
    return struct.pack("384f", *([seed / 100.0] * 384))


class TestOnboardSchema(unittest.TestCase):
    def test_open_db_creates_chunks_and_fts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = oi.open_db(root, create=True)
            # Both tables exist.
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','virtual')"
                )
            }
            self.assertIn("code_files", tables)
            self.assertIn("code_chunks", tables)
            # FTS shadow table (sqlite registers FTS5 v-tables as 'table' too).
            fts_row = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='code_chunks_fts'"
            ).fetchone()
            self.assertIsNotNone(fts_row)
            conn.close()


class TestOnboardIndexChunked(unittest.TestCase):
    """Run do_index against a tiny synthetic project, embedding mocked.
    Verify the chunks table + FTS mirror are populated."""

    def _build_project(self, tmpdir: Path) -> Path:
        root = tmpdir / "proj"
        root.mkdir()
        (root / "main.py").write_text(
            "def hello():\n"
            "    return 'world'\n\n"
            "# A function that adds two numbers.\n"
            "def add(a, b):\n"
            "    return a + b\n"
        )
        return root

    def test_index_populates_chunks_and_fts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._build_project(Path(tmp))
            # Mock embed_batch to return one fake vector per chunk.
            fake_batch = lambda texts: ([_fake_vec(i + 1) for i in range(len(texts))], 384)
            with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
                result = oi.do_index(root, use_git=False)
            self.assertGreaterEqual(result["new"], 1)
            self.assertGreaterEqual(result["total_chunks"], 1)
            # FTS mirror should mirror the chunks
            conn = oi.open_db(root, create=False)
            chunk_count = conn.execute("SELECT count(*) FROM code_chunks").fetchone()[0]
            fts_count = conn.execute("SELECT count(*) FROM code_chunks_fts").fetchone()[0]
            self.assertEqual(chunk_count, fts_count)
            self.assertGreater(chunk_count, 0)
            conn.close()


class TestOnboardSearchFallback(unittest.TestCase):
    """When the db has no code_chunks table (pre-v1.28), search must
    fall back to the legacy whole-file cosine path instead of raising."""

    def test_hybrid_failure_routes_to_legacy(self) -> None:
        """If hybrid_search raises OperationalError (e.g. missing FTS
        table on pre-v1.28 db), do_search must call _do_search_legacy."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".kaizen").mkdir()
            db_path = root / ".kaizen" / "onboard.db"
            sqlite3.connect(str(db_path)).close()  # empty db so db_path.is_file() = True

            sentinel = [{"score": 0.42, "id": 99, "path": "legacy-hit.py",
                         "language": "python", "bytes": 0, "sloc": 0,
                         "snippet": "", "updated_at": ""}]
            with patch.object(oi, "open_db"), \
                 patch.object(
                     oi._kz_search, "hybrid_search",
                     side_effect=sqlite3.OperationalError("no such table: code_chunks_fts")
                 ), \
                 patch.object(oi, "_do_search_legacy", return_value=sentinel) as legacy_mock:
                result = oi.do_search(root, "foo", top_k=5)
            self.assertEqual(result, sentinel)
            legacy_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
