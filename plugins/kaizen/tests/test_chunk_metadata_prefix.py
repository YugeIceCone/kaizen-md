"""Tests for O3 — metadata-rich passage prefix.

`build_metadata_prefix` constructs a ~30-token provenance preamble.
`apply_passage_prefix_with_metadata` wires it onto a chunk's text
alongside the existing model-asymmetric `search_document: ` marker.
`apply_passage_prefix_batch_with_metadata` is the batch entry point used
by onboard's insert path.

Run:
    python3 -m unittest tests.test_chunk_metadata_prefix -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _chunk as kz_chunk  # noqa: E402

class TestBuildMetadataPrefix(unittest.TestCase):
    def test_full_metadata(self):
        out = kz_chunk.build_metadata_prefix(
            path="src/x.py",
            language="python",
            kind="code",
            symbol="foo",
        )
        self.assertIn("file: src/x.py", out)
        self.assertIn("language: python", out)
        self.assertIn("kind: code", out)
        self.assertIn("symbol: foo", out)
        self.assertTrue(out.endswith("---\n"))

    def test_skips_empty_fields(self):
        out = kz_chunk.build_metadata_prefix(
            path="src/x.py",
            language="python",
            # kind + symbol empty
        )
        self.assertIn("file: src/x.py", out)
        self.assertIn("language: python", out)
        self.assertNotIn("kind:", out)
        self.assertNotIn("symbol:", out)

    def test_returns_empty_when_no_fields(self):
        out = kz_chunk.build_metadata_prefix()
        self.assertEqual(out, "")

    def test_compact_token_budget(self):
        """A reasonable metadata block is well under 30 tokens."""
        out = kz_chunk.build_metadata_prefix(
            path="a/b/c/long/path/file.py",
            language="typescript",
            kind="doc",
            symbol="MyClass.method",
        )
        # Conservative: under 200 chars. Typical tokenizer: 30-50 tokens.
        self.assertLess(len(out), 200)

class TestApplyPassagePrefixWithMetadata(unittest.TestCase):
    def test_prepends_marker_then_metadata_then_text(self):
        out = kz_chunk.apply_passage_prefix_with_metadata(
            "def foo(): pass",
            path="x.py",
            language="python",
            kind="code",
        )
        self.assertTrue(out.startswith(kz_chunk.PASSAGE_PREFIX))
        idx_meta = out.index("file: x.py")
        idx_body = out.index("def foo(): pass")
        self.assertLess(idx_meta, idx_body, "metadata must precede body")

    def test_idempotent_when_already_prefixed(self):
        prefixed = kz_chunk.PASSAGE_PREFIX + "already done"
        out = kz_chunk.apply_passage_prefix_with_metadata(
            prefixed, path="x.py", language="python"
        )
        self.assertEqual(out, prefixed)

    def test_works_with_no_metadata(self):
        """Falls back to plain passage prefix when all metadata is empty."""
        out = kz_chunk.apply_passage_prefix_with_metadata("body text")
        self.assertEqual(out, kz_chunk.PASSAGE_PREFIX + "body text")

    def test_preserves_text_payload(self):
        out = kz_chunk.apply_passage_prefix_with_metadata(
            "raw chunk body\nwith newlines",
            path="x.rs",
            language="rust",
            kind="doc",
        )
        self.assertIn("raw chunk body\nwith newlines", out)

class TestApplyPassagePrefixBatchWithMetadata(unittest.TestCase):
    def test_processes_chunks_in_order(self):
        items = [
            {"text": "first", "path": "a.py", "language": "python", "kind": "code"},
            {"text": "second", "path": "b.rs", "language": "rust", "kind": "doc"},
            {"text": "third", "path": "c.ts", "language": "typescript", "kind": "code"},
        ]
        out = kz_chunk.apply_passage_prefix_batch_with_metadata(items)
        self.assertEqual(len(out), 3)
        self.assertIn("first", out[0])
        self.assertIn("file: a.py", out[0])
        self.assertIn("second", out[1])
        self.assertIn("kind: doc", out[1])
        self.assertIn("third", out[2])

    def test_handles_missing_optional_keys(self):
        items = [{"text": "only-text"}]  # no path/language/kind
        out = kz_chunk.apply_passage_prefix_batch_with_metadata(items)
        self.assertEqual(len(out), 1)
        # No metadata block, but still has the passage marker.
        self.assertTrue(out[0].startswith(kz_chunk.PASSAGE_PREFIX))
        self.assertIn("only-text", out[0])

    def test_empty_input(self):
        self.assertEqual(
            kz_chunk.apply_passage_prefix_batch_with_metadata([]), []
        )

class TestBackwardCompatPlainBatch(unittest.TestCase):
    """The old apply_passage_prefix_batch must keep working — onboard's
    pre-O3 callers and the embed-rerank MCP both use it."""

    def test_plain_batch_unchanged(self):
        out = kz_chunk.apply_passage_prefix_batch(["a", "b", "c"])
        self.assertEqual(len(out), 3)
        for s in out:
            self.assertTrue(s.startswith(kz_chunk.PASSAGE_PREFIX))

if __name__ == "__main__":
    unittest.main()
