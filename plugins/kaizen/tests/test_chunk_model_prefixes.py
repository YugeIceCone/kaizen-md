"""Tests for E1 — model-aware asymmetric prefix detection.

`detect_model_family(model)` substring-matches against known embedding
model patterns. `prefixes_for_model(model)` returns (query, passage)
prefixes. `apply_query_prefix` / `apply_passage_prefix` route through
both for backward-compatible model-aware behavior.

Run:
    python3 -m unittest tests.test_chunk_model_prefixes -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _chunk as kz_chunk  # noqa: E402

class TestDetectModelFamily(unittest.TestCase):
    cases = [
        ("nomic-embed-text", "nomic"),
        ("nomic-embed-v2", "nomic"),
        ("all-MiniLM-L6-v2", "nomic"),  # minilm → nomic-compatible
        ("mxbai-embed-large-v1", "nomic"),
        ("bge-small-en-v1.5", "bge"),
        ("BAAI/bge-large-en", "bge"),
        ("intfloat/e5-base-v2", "e5"),
        ("intfloat/e5-mistral-7b-instruct", "e5"),
        ("jinaai/jina-embeddings-v3", "jina"),
        ("Alibaba-NLP/gte-Qwen2-7B-instruct", "gte-qwen"),
        ("Qwen3-Embedding-8B", "gte-qwen"),
        ("", "generic"),
        ("random-unknown-model", "generic"),
    ]

    def test_substring_matching(self):
        for model, expected in self.cases:
            with self.subTest(model=model):
                self.assertEqual(
                    kz_chunk.detect_model_family(model), expected
                )

class TestPrefixesForModel(unittest.TestCase):
    def test_nomic_returns_search_query_search_document(self):
        q, p = kz_chunk.prefixes_for_model("nomic-embed-text")
        self.assertEqual(q, "search_query: ")
        self.assertEqual(p, "search_document: ")

    def test_bge_returns_long_query_empty_passage(self):
        q, p = kz_chunk.prefixes_for_model("bge-small-en")
        self.assertIn("Represent this sentence", q)
        self.assertEqual(p, "")

    def test_e5_returns_short_paired(self):
        q, p = kz_chunk.prefixes_for_model("e5-base-v2")
        self.assertEqual(q, "query: ")
        self.assertEqual(p, "passage: ")

    def test_jina_returns_empty_pair(self):
        q, p = kz_chunk.prefixes_for_model("jina-embeddings-v3")
        self.assertEqual(q, "")
        self.assertEqual(p, "")

    def test_gte_qwen_returns_instruct_query(self):
        q, p = kz_chunk.prefixes_for_model("gte-Qwen2-7B")
        self.assertIn("Instruct:", q)
        self.assertIn("Query:", q)
        self.assertEqual(p, "")

    def test_unknown_falls_back_to_nomic(self):
        q, p = kz_chunk.prefixes_for_model("random-unknown")
        self.assertEqual(q, "search_query: ")
        self.assertEqual(p, "search_document: ")

class TestApplyQueryPrefixModelAware(unittest.TestCase):
    def test_nomic_prefix(self):
        out = kz_chunk.apply_query_prefix("hello", "nomic-embed-text")
        self.assertEqual(out, "search_query: hello")

    def test_bge_prefix(self):
        out = kz_chunk.apply_query_prefix("hello", "bge-small")
        self.assertTrue(out.startswith("Represent this sentence"))
        self.assertTrue(out.endswith("hello"))

    def test_e5_prefix(self):
        out = kz_chunk.apply_query_prefix("hello", "e5-base")
        self.assertEqual(out, "query: hello")

    def test_jina_no_prefix(self):
        out = kz_chunk.apply_query_prefix("hello", "jina-embeddings-v3")
        self.assertEqual(out, "hello")  # no transformation

    def test_idempotent_across_model_families(self):
        """If text already has ANY known query prefix, return unchanged
        (cross-model batch safety)."""
        already = "query: foo"  # e5-style
        out = kz_chunk.apply_query_prefix(already, "nomic-embed-text")
        self.assertEqual(out, "query: foo")  # NOT re-prefixed with nomic

    def test_empty_model_uses_default(self):
        """Back-compat: model="" → nomic-style prefix (the legacy default)."""
        out = kz_chunk.apply_query_prefix("hello")
        self.assertEqual(out, "search_query: hello")

class TestApplyPassagePrefixModelAware(unittest.TestCase):
    def test_nomic_passage(self):
        out = kz_chunk.apply_passage_prefix("body", "nomic-embed-text")
        self.assertEqual(out, "search_document: body")

    def test_bge_no_passage_prefix(self):
        """BGE has no passage prefix — text returned unchanged."""
        out = kz_chunk.apply_passage_prefix("body", "bge-small")
        self.assertEqual(out, "body")

    def test_e5_passage_prefix(self):
        out = kz_chunk.apply_passage_prefix("body", "e5-base")
        self.assertEqual(out, "passage: body")

    def test_empty_model_uses_default_passage(self):
        out = kz_chunk.apply_passage_prefix("body")
        self.assertEqual(out, "search_document: body")

class TestApplyPassagePrefixWithMetadataModelAware(unittest.TestCase):
    """The O3 metadata-rich wrapper must also honor E1's model detection."""

    def test_uses_e5_prefix_when_model_is_e5(self):
        out = kz_chunk.apply_passage_prefix_with_metadata(
            "body", path="x.py", language="python",
            model="e5-base",
        )
        self.assertTrue(out.startswith("passage: "))
        self.assertIn("file: x.py", out)
        self.assertTrue(out.endswith("body"))

    def test_uses_nomic_prefix_when_model_empty(self):
        out = kz_chunk.apply_passage_prefix_with_metadata(
            "body", path="x.py", language="python",
        )
        self.assertTrue(out.startswith("search_document: "))

class TestBackCompatConstants(unittest.TestCase):
    """Module-level QUERY_PREFIX / PASSAGE_PREFIX preserve their values
    for callers that import them by name (embed-rerank MCP, ad-hoc)."""

    def test_query_prefix_constant_unchanged(self):
        self.assertEqual(kz_chunk.QUERY_PREFIX, "search_query: ")

    def test_passage_prefix_constant_unchanged(self):
        self.assertEqual(kz_chunk.PASSAGE_PREFIX, "search_document: ")

if __name__ == "__main__":
    unittest.main()
