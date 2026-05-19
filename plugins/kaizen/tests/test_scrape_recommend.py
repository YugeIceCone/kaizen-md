#!/usr/bin/env python3
"""Unit tests for scrape_index.py's v1.29.0 Ollama recommendation picker.

Verifies:
  - OLLAMA_SCRAPE_RECOMMENDATIONS is a well-formed list (shape + ordering)
  - pick_best_chat_model returns the highest-ranked match
  - pick_best_chat_model falls back to first non-embed when no rec matches
  - pick_best_chat_model returns None when only embed models are installed
  - _model_name_matches accepts exact, `:tag`, `-suffix` variants

Run:
    python3 -m unittest tests.test_scrape_recommend -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "indexers"))

import scrape_index as si  # noqa: E402


class TestRecommendationsShape(unittest.TestCase):
    def test_list_is_ranked(self) -> None:
        # Updated 2026-05-12 (v1.29.2): granite4.1:8b promoted to winner —
        # only pick whose official model card explicitly documents
        # "structured JSON output", which matches ScrapeGraphAI's exact
        # workload (HTML → JSON via format=json). qwen3.5:9b stays in the
        # list as the generalist fallback. Keep this assertion narrow so
        # future bumps don't have to touch every rank.
        self.assertEqual(si.OLLAMA_SCRAPE_RECOMMENDATIONS[0]["name"], "granite4.1:8b")
        self.assertEqual(si.OLLAMA_SCRAPE_RECOMMENDATIONS[0]["tier"], "winner")

    def test_each_entry_well_formed(self) -> None:
        required = {"name", "size_gb", "ctx_k", "tier", "why"}
        for rec in si.OLLAMA_SCRAPE_RECOMMENDATIONS:
            self.assertEqual(set(rec.keys()), required, f"{rec.get('name')} missing keys")
            self.assertIsInstance(rec["size_gb"], (int, float))
            self.assertIsInstance(rec["ctx_k"], int)
            self.assertGreater(len(rec["why"]), 10)

    def test_names_unique(self) -> None:
        names = [r["name"] for r in si.OLLAMA_SCRAPE_RECOMMENDATIONS]
        self.assertEqual(len(names), len(set(names)))


class TestModelNameMatches(unittest.TestCase):
    def test_exact(self) -> None:
        self.assertTrue(si._model_name_matches("qwen3.5:9b", "qwen3.5:9b"))

    def test_tag_suffix(self) -> None:
        # `qwen3.5:9b-instruct-q4_0` should match `qwen3.5:9b`
        self.assertTrue(si._model_name_matches("qwen3.5:9b-instruct-q4_0", "qwen3.5:9b"))

    def test_colon_suffix(self) -> None:
        # `qwen3.5:9b:custom` matches `qwen3.5:9b`
        self.assertTrue(si._model_name_matches("qwen3.5:9b:custom", "qwen3.5:9b"))

    def test_no_match(self) -> None:
        self.assertFalse(si._model_name_matches("llama3.1:8b", "qwen3.5:9b"))

    def test_family_only_no_loose_match(self) -> None:
        # `qwen3.5` should NOT match `qwen3.5:9b` (different size)
        self.assertFalse(si._model_name_matches("qwen3.5", "qwen3.5:9b"))


class TestPickBestChatModel(unittest.TestCase):
    def test_empty_returns_none(self) -> None:
        self.assertIsNone(si.pick_best_chat_model([]))

    def test_only_embed_returns_none(self) -> None:
        self.assertIsNone(si.pick_best_chat_model(["nomic-embed-text", "bge-small-en"]))

    def test_winner_chosen_over_lower_rank(self) -> None:
        # qwen3.5:9b is rank 2, granite4.1:8b is rank 1 (winner) post-v1.29.2
        out = si.pick_best_chat_model(["qwen3.5:9b", "granite4.1:8b"])
        self.assertEqual(out, "granite4.1:8b")

    def test_winner_chosen_regardless_of_install_order(self) -> None:
        # Order in `installed` list shouldn't matter; ranking does.
        out = si.pick_best_chat_model(["granite4.1:8b", "qwen3.5:9b"])
        self.assertEqual(out, "granite4.1:8b")

    def test_falls_back_to_lower_ranked_when_winner_missing(self) -> None:
        # No granite4.1:8b installed → qwen3.5:9b (rank 2) wins over qwen3.5:4b (rank 4)
        out = si.pick_best_chat_model(["qwen3.5:4b", "qwen3.5:9b"])
        self.assertEqual(out, "qwen3.5:9b")

    def test_falls_back_to_arbitrary_when_no_rec(self) -> None:
        # No recommended chat model is installed; first non-embed wins.
        out = si.pick_best_chat_model(["mistral:7b", "nomic-embed-text"])
        self.assertEqual(out, "mistral:7b")

    def test_skips_embed_in_fallback(self) -> None:
        # Embed comes first but should be skipped; chat comes second and wins.
        out = si.pick_best_chat_model(["nomic-embed-text", "mistral:7b"])
        self.assertEqual(out, "mistral:7b")

    def test_loose_match_on_tag_suffix(self) -> None:
        # Installed model has a quant suffix; should still match the rec.
        out = si.pick_best_chat_model(["qwen3.5:9b-instruct-q4_0"])
        self.assertEqual(out, "qwen3.5:9b-instruct-q4_0")


if __name__ == "__main__":
    unittest.main()
