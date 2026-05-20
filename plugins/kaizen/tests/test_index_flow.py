#!/usr/bin/env python3
"""Tests for index_flow.py — pocketflow-shaped ingest pipeline.

Run:
    python3 -m unittest tests.test_index_flow -v
"""

from __future__ import annotations

import asyncio
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "indexers"))

try:
    import numpy  # noqa: F401
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

import onboard_index as oi  # noqa: E402
import index_flow as ix  # noqa: E402

requires_numpy = unittest.skipUnless(NUMPY_AVAILABLE, "numpy not installed")

def _vec(seed: int = 1) -> bytes:
    return struct.pack("384f", *([seed / 100.0] * 384))

class TestDiscoverNode(unittest.TestCase):
    def test_lists_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            (root / "b.rs").write_text("pub fn f() {}\n")
            (root / "README.md").write_text("text")  # NOT in LANG_TABLE
            node = ix.DiscoverNode()
            store = {"root": root, "use_git": False}
            asyncio.run(node.run_async(store))
            paths = sorted(p.name for p in store["candidate_files"])
            self.assertEqual(paths, ["a.py", "b.rs"])
            self.assertEqual(store["candidate_count"], 2)

class TestDumpNode(unittest.TestCase):
    def test_writes_to_code_files_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            (root / "b.py").write_text("y = 2\n")
            node = ix.DumpNode()
            store = {"root": root, "use_git": False}
            asyncio.run(node.run_async(store))
            self.assertEqual(store["files_total"], 2)
            self.assertEqual(store["errors"], 0)
            conn = oi.open_db(root, create=False)
            n = conn.execute("SELECT COUNT(*) FROM code_files_raw").fetchone()[0]
            self.assertEqual(n, 2)
            conn.close()

@requires_numpy
class TestEndToEndIndexFlow(unittest.TestCase):
    def test_full_pipeline_populates_db_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                "def hello():\n    return 'world'\n" * 5
            )
            (root / "lib.py").write_text(
                "class Thing:\n    pass\n" * 5
            )
            fake_batch = lambda texts: ([_vec(i + 1) for i in range(len(texts))], 384)
            with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
                report = ix.index(root, use_git=False)
            self.assertEqual(report["new"], 2)
            self.assertEqual(report["errors"], 0)
            self.assertGreater(report["total_chunks"], 0)
            self.assertTrue(report.get("optimized"))
            conn = oi.open_db(root, create=False)
            n_files = conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
            self.assertEqual(n_files, 2)
            # int8 quant column populated when embedding_q8 exists.
            n_q8 = conn.execute(
                "SELECT COUNT(*) FROM code_chunks WHERE embedding_q8 IS NOT NULL"
            ).fetchone()[0]
            self.assertGreater(n_q8, 0,
                               "embedding_q8 should be populated on fresh dbs")
            conn.close()

class TestSkipOptimize(unittest.TestCase):
    @requires_numpy
    def test_optimize_disabled_via_store_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n" * 5)
            fake_batch = lambda texts: ([_vec(i + 1) for i in range(len(texts))], 384)
            with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
                report = ix.index(root, use_git=False, optimize=False)
            self.assertFalse(report["optimized"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
