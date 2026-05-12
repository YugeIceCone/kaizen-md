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

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "kaizen" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import scrape_index as si  # noqa: E402


class TestRecommendationsShape(unittest.TestCase):
    def test_list_is_ranked(self) -> None:
        self.assertEqual(si.OLLAMA_SCRAPE_RECOMMENDATIONS[0]["name"], "qwen2.5:7b")
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
        self.assertTrue(si._model_name_matches("qwen2.5:7b", "qwen2.5:7b"))

    def test_tag_suffix(self) -> None:
        # `qwen2.5:7b-instruct-q4_0` should match `qwen2.5:7b`
        self.assertTrue(si._model_name_matches("qwen2.5:7b-instruct-q4_0", "qwen2.5:7b"))

    def test_colon_suffix(self) -> None:
        # `qwen2.5:7b:custom` matches `qwen2.5:7b`
        self.assertTrue(si._model_name_matches("qwen2.5:7b:custom", "qwen2.5:7b"))

    def test_no_match(self) -> None:
        self.assertFalse(si._model_name_matches("llama3.1:8b", "qwen2.5:7b"))

    def test_family_only_no_loose_match(self) -> None:
        # `qwen2.5` should NOT match `qwen2.5:7b` (different size)
        self.assertFalse(si._model_name_matches("qwen2.5", "qwen2.5:7b"))


class TestPickBestChatModel(unittest.TestCase):
    def test_empty_returns_none(self) -> None:
        self.assertIsNone(si.pick_best_chat_model([]))

    def test_only_embed_returns_none(self) -> None:
        self.assertIsNone(si.pick_best_chat_model(["nomic-embed-text", "bge-small-en"]))

    def test_winner_chosen_over_lower_rank(self) -> None:
        # llama3.1:8b is rank 2, qwen2.5:7b is rank 1 (winner)
        out = si.pick_best_chat_model(["llama3.1:8b", "qwen2.5:7b"])
        self.assertEqual(out, "qwen2.5:7b")

    def test_winner_chosen_regardless_of_install_order(self) -> None:
        # Order in `installed` list shouldn't matter; ranking does.
        out = si.pick_best_chat_model(["qwen2.5:7b", "llama3.1:8b"])
        self.assertEqual(out, "qwen2.5:7b")

    def test_falls_back_to_lower_ranked_when_winner_missing(self) -> None:
        out = si.pick_best_chat_model(["llama3.1:8b", "granite3.3:8b"])
        self.assertEqual(out, "llama3.1:8b")  # rank 2 beats rank 4

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
        out = si.pick_best_chat_model(["qwen2.5:7b-instruct-q4_0"])
        self.assertEqual(out, "qwen2.5:7b-instruct-q4_0")


if __name__ == "__main__":
    unittest.main()
