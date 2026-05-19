"""Tests for E2 — cross-encoder reranking + M4 rerank MCP wrapper.

`cross_encoder_rerank` uses an injectable `score_fn` to stay independent
of sentence-transformers in the test environment (the real model pulls
80-280 MB of weights).

Run:
    python3 -m unittest tests.test_cross_encoder_rerank -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "mcp"))

import _search as kz_search  # noqa: E402


def _stub_score_fn(score_map: dict[str, float]):
    """Build a score_fn that returns a fixed score per text snippet."""
    def _fn(query, texts):
        return [score_map.get(t, 0.0) for t in texts]
    return _fn


class TestCrossEncoderRerank(unittest.TestCase):
    def test_reorders_by_score(self):
        candidates = [(1, "low"), (2, "medium"), (3, "high")]
        scores = _stub_score_fn({"low": 0.1, "medium": 0.5, "high": 0.9})
        out = kz_search.cross_encoder_rerank(
            "q", candidates, score_fn=scores
        )
        ids = [rid for rid, _ in out]
        self.assertEqual(ids, [3, 2, 1])

    def test_top_k_caps_results(self):
        candidates = [(i, f"t{i}") for i in range(10)]
        scores = _stub_score_fn({f"t{i}": float(i) for i in range(10)})
        out = kz_search.cross_encoder_rerank(
            "q", candidates, top_k=3, score_fn=scores
        )
        self.assertEqual(len(out), 3)
        ids = [rid for rid, _ in out]
        # Top 3 by score: 9, 8, 7
        self.assertEqual(ids, [9, 8, 7])

    def test_empty_candidates_returns_empty(self):
        out = kz_search.cross_encoder_rerank("q", [], score_fn=lambda q, t: [])
        self.assertEqual(out, [])

    def test_returns_scores_as_floats(self):
        scores = _stub_score_fn({"x": 0.42})
        out = kz_search.cross_encoder_rerank(
            "q", [(1, "x")], score_fn=scores
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 1)
        self.assertAlmostEqual(out[0][1], 0.42)

    def test_validates_score_fn_output_length(self):
        candidates = [(1, "a"), (2, "b"), (3, "c")]
        # Stub returning wrong length should raise
        bad = lambda q, t: [0.5]  # 1 score for 3 candidates
        with self.assertRaises(ValueError):
            kz_search.cross_encoder_rerank("q", candidates, score_fn=bad)

    def test_no_score_fn_no_model_returns_input_order(self):
        """When sentence-transformers is unavailable AND no stub provided,
        function should gracefully return input order (no crash). Force
        the no-model path by setting _cross_encoder=None and mocking
        import."""
        # Save + restore the module cache so test isolation holds
        saved = kz_search._cross_encoder
        kz_search._cross_encoder = None
        # Best-effort: if sentence-transformers IS installed, this test
        # would actually load the model. Detect + skip in that case.
        try:
            import sentence_transformers  # noqa: F401
            self.skipTest("sentence-transformers installed; can't test fallback")
        except ImportError:
            pass
        try:
            out = kz_search.cross_encoder_rerank(
                "q", [(1, "a"), (2, "b")],
            )
        finally:
            kz_search._cross_encoder = saved
        # Returns input order with score=0
        self.assertEqual(len(out), 2)
        self.assertEqual([rid for rid, _ in out], [1, 2])
        self.assertEqual([s for _, s in out], [0.0, 0.0])


class TestRerankMcpTools(unittest.TestCase):
    """Smoke + delegation tests for the embed_rerank MCP wrapper."""

    def _import(self):
        if "rerank_mcp" in sys.modules:
            del sys.modules["rerank_mcp"]
        import rerank_mcp
        return rerank_mcp

    def test_module_loads_and_exposes_tools(self):
        m = self._import()
        self.assertTrue(hasattr(m, "embed_rerank"))
        self.assertTrue(hasattr(m, "embed_rerank_status"))

    def test_embed_rerank_passes_through_to_search(self):
        m = self._import()
        # Monkey-patch the underlying rerank with a stub
        original = kz_search.cross_encoder_rerank
        kz_search.cross_encoder_rerank = lambda q, c, **kw: [
            (c[0][0], 0.9), (c[1][0], 0.1),
        ] if len(c) >= 2 else []
        try:
            out = asyncio.run(m.embed_rerank(
                "q",
                [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}],
                top_k=5,
            ))
        finally:
            kz_search.cross_encoder_rerank = original
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["id"], "a")
        self.assertEqual(out[0]["text"], "first")
        self.assertEqual(out[0]["score"], 0.9)

    def test_embed_rerank_empty_inputs(self):
        m = self._import()
        out = asyncio.run(m.embed_rerank("", [], top_k=5))
        self.assertEqual(out, [])
        out = asyncio.run(m.embed_rerank("q", [], top_k=5))
        self.assertEqual(out, [])

    def test_status_reports_model(self):
        m = self._import()
        s = asyncio.run(m.embed_rerank_status())
        self.assertIn("model", s)
        self.assertIn("sentence_transformers_available", s)
        # Default model is the MiniLM cross-encoder
        self.assertIn("MiniLM", s["model"])

    def test_status_honors_env_override(self):
        m = self._import()
        os.environ["KAIZEN_RERANK_MODEL"] = "BAAI/bge-reranker-base"
        try:
            s = asyncio.run(m.embed_rerank_status())
        finally:
            del os.environ["KAIZEN_RERANK_MODEL"]
        self.assertEqual(s["model"], "BAAI/bge-reranker-base")


class TestRerankMcpRegistration(unittest.TestCase):
    def test_mcp_json_lists_rerank_server(self):
        import json
        with open(PLUGIN_ROOT / ".mcp.json") as f:
            data = json.load(f)
        # All domain servers are composed through the kaizen gateway
        self.assertIn("kaizen", data["mcpServers"])
        joined = " ".join(data["mcpServers"]["kaizen"]["args"])
        self.assertIn("gateway.py", joined)
        import gateway
        module_names = [m for _, m in gateway.SUBSERVERS]
        self.assertIn("rerank_mcp", module_names)


if __name__ == "__main__":
    unittest.main()
