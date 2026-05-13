#!/usr/bin/env python3
"""Tests for search_flow.py — pocketflow-shaped semantic-search pipeline.

Coverage:
  - EmbedQueryNode rejects empty query
  - FusionNode honors `fusion=rrf` route
  - CitationNode resolves code_chunks rows → result dicts
  - build_search_flow assembles a valid graph
  - End-to-end: synthetic 3-file project, mocked embed_batch + embed_one,
    full flow produces ranked results.

Embeddings are mocked deterministically so we don't need a live
sentence-transformers backend.

Run:
    python3 -m unittest tests.test_search_flow -v
"""

from __future__ import annotations

import asyncio
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

try:
    import numpy  # noqa: F401
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

import onboard_index as oi  # noqa: E402
import search_flow as sf  # noqa: E402

requires_numpy = unittest.skipUnless(
    NUMPY_AVAILABLE,
    "numpy not installed; run tests under `uv run --script` to exercise the embed path",
)


def _vec(seed: int = 1) -> bytes:
    """Deterministic 384-dim float32 vector for mocking embeds."""
    import math
    base = seed / 100.0
    floats = [base + 0.001 * math.sin(i) for i in range(384)]
    return struct.pack(f"{len(floats)}f", *floats)


def _seed_index(root: Path) -> None:
    """Seed an onboard.db with three small Rust files using mocked embeds."""
    (root / "main.rs").write_text(
        "pub fn validate_token(t: &str) -> bool {\n    t.starts_with(\"Bearer\")\n}\n"
    )
    (root / "embed.rs").write_text(
        "pub fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {\n"
        "    let mut sum = 0.0;\n"
        "    for i in 0..a.len() {\n"
        "        sum += a[i] * b[i];\n"
        "    }\n"
        "    sum\n"
        "}\n"
    )
    (root / "search.rs").write_text(
        "pub fn hybrid_search(query: &str, alpha: f32) -> Vec<String> {\n"
        "    vec![]\n"
        "}\n"
    )
    fake_batch = lambda texts: ([_vec(i + 1) for i in range(len(texts))], 384)
    with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
        oi.do_dump(root, use_git=False)
        oi.do_filter(root)


class TestEmbedQueryNode(unittest.TestCase):
    def test_rejects_empty_query(self) -> None:
        node = sf.EmbedQueryNode()
        with self.assertRaises(ValueError):
            asyncio.run(node.prep_async({"query": ""}))

    @requires_numpy
    def test_writes_normalized_vector_to_store(self) -> None:
        node = sf.EmbedQueryNode()

        def fake_embed_one(text: str):
            return _vec(42), 384

        store: dict = {"query": "auth token"}
        with patch.object(sf._kz_embed, "embed_one", side_effect=fake_embed_one):
            asyncio.run(node.run_async(store))
        import numpy as np
        v = store["query_vec"]
        self.assertEqual(v.shape, (384,))
        # Already normalized (unit length, within rounding).
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)


class TestFusionNode(unittest.TestCase):
    def test_linear_fusion_default(self) -> None:
        node = sf.FusionNode()
        store = {
            "dense_pool": [(1, 0.9), (2, 0.8)],
            "bm25_pool": [(2, 0.5), (3, 0.1)],
            "alpha": 0.5, "fusion": "linear", "top_k": 5,
        }
        action = asyncio.run(node.run_async(store))
        self.assertEqual(action, "citation")
        ids = [rid for rid, _ in store["fused"]]
        self.assertIn(2, ids)  # overlap → high fused score
        self.assertIn(1, ids)

    def test_rrf_path(self) -> None:
        node = sf.FusionNode()
        store = {
            "dense_pool": [(1, 0.9), (2, 0.8), (3, 0.7)],
            "bm25_pool":  [(3, 0.5), (2, 0.4), (1, 0.3)],
            "alpha": 0.5, "fusion": "rrf", "top_k": 3,
        }
        asyncio.run(node.run_async(store))
        # All three should appear; RRF with equal weights = boost overlap
        self.assertEqual(len({rid for rid, _ in store["fused"]}), 3)

    def test_routes_to_rerank_when_opt_in(self) -> None:
        node = sf.FusionNode()
        store = {
            "dense_pool": [(1, 0.9)],
            "bm25_pool": [(1, 0.5)],
            "rerank": True,
            "alpha": 0.5, "fusion": "linear", "top_k": 5,
        }
        action = asyncio.run(node.run_async(store))
        self.assertEqual(action, "rerank")


class TestCitationNode(unittest.TestCase):
    def test_resolves_chunks_to_result_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_index(root)
            # Pull two chunk ids that should exist (seeded as ids 1,2).
            conn = oi.open_db(root, create=False)
            chunk_rows = conn.execute(
                "SELECT id FROM code_chunks ORDER BY id LIMIT 2"
            ).fetchall()
            conn.close()
            self.assertEqual(len(chunk_rows), 2)
            ranked = [(chunk_rows[0]["id"], 0.9), (chunk_rows[1]["id"], 0.7)]
            node = sf.CitationNode()
            store = {"root": root, "fused": ranked, "_base_table": "code_chunks"}
            asyncio.run(node.run_async(store))
            results = store["results"]
            self.assertEqual(len(results), 2)
            for r in results:
                self.assertIn("path", r)
                self.assertIn("char_range", r)
                self.assertIn("matched_chunk_idx", r)
                self.assertIn("score", r)


class TestBuildSearchFlow(unittest.TestCase):
    def test_assembles_valid_graph(self) -> None:
        f = sf.build_search_flow()
        # Walk the graph from start; every reachable (node, action) should
        # resolve to a registered successor or terminate (no action).
        seen: set = set()
        stack = [f.start]
        while stack:
            n = stack.pop()
            if id(n) in seen:
                continue
            seen.add(id(n))
            for (src, _action), nxt in f.successors.items():
                if src is n:
                    stack.append(nxt)
        # Five nodes total: embed, fan-out, fusion, rerank, citation.
        self.assertEqual(len(seen), 5)


class TestEndToEnd(unittest.TestCase):
    @requires_numpy
    def test_full_flow_returns_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_index(root)

            def fake_embed_one(text: str):
                return _vec(2), 384  # close to file #2 (embed.rs) by seed

            with patch.object(sf._kz_embed, "embed_one", side_effect=fake_embed_one):
                results = sf.search(root, "cosine similarity", top_k=3)
            self.assertGreater(len(results), 0)
            self.assertLessEqual(len(results), 3)
            for r in results:
                self.assertIn("path", r)
                self.assertIn("score", r)
            # Timing metadata is captured.
            self.assertIsInstance(results[0]["score"], float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
