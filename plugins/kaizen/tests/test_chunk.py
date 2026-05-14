#!/usr/bin/env python3
"""Unit tests for _chunk.py — sentence-boundary chunking (v1.27.0+).

Verifies:
  - Empty / whitespace input → []
  - Tiny doc (< cap) → one chunk
  - Long doc → multiple chunks at sentence boundaries
  - char_start / char_end map back to the source correctly
  - Abbreviations don't cause false sentence splits
  - Mega-sentence longer than cap → its own chunk (no mid-split)
  - chunk_into_dicts shape

Run:
    python3 -m unittest tests.test_chunk -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import _chunk  # noqa: E402


class TestChunkText(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(_chunk.chunk_text(""), [])
        self.assertEqual(_chunk.chunk_text("   \n  \n   "), [])

    def test_tiny_doc_single_chunk(self) -> None:
        text = "Hello world. This is a short doc."
        chunks = _chunk.chunk_text(text, max_tokens=512)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_idx, 0)
        self.assertEqual(chunks[0].char_start, 0)
        self.assertEqual(chunks[0].char_end, len(text))
        self.assertIn("Hello world", chunks[0].text)

    def test_long_doc_multi_chunk(self) -> None:
        # ~600 chars per "para" × 5 = 3000 chars > 512*4 = 2048 cap → splits.
        sentence = "The quick brown fox jumps over the lazy dog. " * 10
        text = (sentence + "\n\n") * 5
        chunks = _chunk.chunk_text(text, max_tokens=512)
        self.assertGreater(len(chunks), 1)
        # chunk_idx monotonic
        for i, c in enumerate(chunks):
            self.assertEqual(c.chunk_idx, i)

    def test_char_offsets_reconstruct(self) -> None:
        text = (
            "First paragraph here with several sentences. "
            "Quick brown fox. Lazy dog.\n\n"
            "Second paragraph. " * 30
        )
        chunks = _chunk.chunk_text(text, max_tokens=64)  # tight cap → multi-chunk
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            # The chunk text is stripped, but the offsets bound the original slice
            slice_ = text[c.char_start:c.char_end]
            self.assertIn(c.text[:20].strip(), slice_)
            self.assertGreaterEqual(c.char_end, c.char_start)

    def test_abbreviation_not_a_boundary(self) -> None:
        # "Dr. Smith" should not split between "Dr." and "Smith"
        text = "Dr. Smith examined the patient. The diagnosis was clear."
        chunks = _chunk.chunk_text(text, max_tokens=512)
        self.assertEqual(len(chunks), 1)
        # The actual sentence count in the chunk should be 2 ("examined…" + "diagnosis…")
        # not 3 with "Dr." treated as its own.
        self.assertIn("Dr. Smith", chunks[0].text)

    def test_mega_sentence_emits_one_chunk(self) -> None:
        # A single sentence longer than max_chars should emit alone (no mid-split).
        text = ("a" * 10) * 50  # 500 chars, no boundaries
        chunks = _chunk.chunk_text(text, max_tokens=64)  # 64*4 = 256 char cap
        self.assertEqual(len(chunks), 1)
        self.assertGreater(len(chunks[0].text), 256)

    def test_into_dicts_shape(self) -> None:
        text = "Sentence one. Sentence two. Sentence three."
        out = _chunk.chunk_into_dicts(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0].keys()), {"text", "char_start", "char_end", "chunk_idx"})


class TestPrefixes(unittest.TestCase):
    def test_query_prefix_idempotent(self) -> None:
        q = "find me a function"
        once = _chunk.apply_query_prefix(q)
        twice = _chunk.apply_query_prefix(once)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith("search_query:"))

    def test_passage_prefix_idempotent(self) -> None:
        p = "the function does X"
        once = _chunk.apply_passage_prefix(p)
        twice = _chunk.apply_passage_prefix(once)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith("search_document:"))

    def test_passage_prefix_batch(self) -> None:
        out = _chunk.apply_passage_prefix_batch(["a", "b", "c"])
        self.assertEqual(len(out), 3)
        for s in out:
            self.assertTrue(s.startswith("search_document:"))


if __name__ == "__main__":
    unittest.main()
