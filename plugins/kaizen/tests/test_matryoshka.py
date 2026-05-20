"""Tests for E5 — matryoshka embeddings (truncatable dim).

`maybe_truncate_matryoshka` is the entry point. It's a no-op unless
BOTH KAIZEN_EMBED_MATRYOSHKA_DIM > 0 AND the model name matches a
known matryoshka family. Pure-numpy operation; no model loading
required.

Run:
    python3 -m unittest tests.test_matryoshka -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
import _embed as kz_embed  # noqa: E402

class _EnvSandbox:
    KEY = "KAIZEN_EMBED_MATRYOSHKA_DIM"

    def __enter__(self):
        self._saved = os.environ.pop(self.KEY, None)
        return self

    def __exit__(self, *_):
        if self._saved is not None:
            os.environ[self.KEY] = self._saved

class TestIsMatryoshkaModel(unittest.TestCase):
    def test_matches_known_families(self):
        for name in (
            "mxbai-embed-large-v1",
            "mixedbread-ai/mxbai-embed",
            "nomic-embed-v2",
            "BAAI/bge-m3",
            "intfloat/e5-mistral-7b-instruct",
        ):
            with self.subTest(name=name):
                self.assertTrue(kz_embed.is_matryoshka_model(name))

    def test_rejects_unknown(self):
        for name in (
            "all-MiniLM-L6-v2",
            "bge-small-en",  # NOT bge-m3
            "",
            None,
        ):
            with self.subTest(name=name):
                self.assertFalse(kz_embed.is_matryoshka_model(name))

    def test_case_insensitive(self):
        self.assertTrue(kz_embed.is_matryoshka_model("MXBAI-Embed-Large"))

class TestMaybeTruncate(unittest.TestCase):
    def test_noop_when_env_unset(self):
        with _EnvSandbox():
            vec = list(range(1024))
            self.assertEqual(
                kz_embed.maybe_truncate_matryoshka(vec, "mxbai-embed-large"),
                vec,
            )

    def test_noop_when_env_zero(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "0"
            vec = list(range(1024))
            self.assertEqual(
                kz_embed.maybe_truncate_matryoshka(vec, "mxbai-embed-large"),
                vec,
            )

    def test_noop_when_model_not_matryoshka(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "64"
            vec = list(range(384))
            self.assertEqual(
                kz_embed.maybe_truncate_matryoshka(vec, "all-MiniLM-L6-v2"),
                vec,
            )

    def test_truncates_when_both_conditions_met(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "64"
            vec = list(range(1024))
            out = kz_embed.maybe_truncate_matryoshka(vec, "mxbai-embed-large")
            self.assertEqual(len(out), 64)
            self.assertEqual(out, list(range(64)))

    def test_no_truncate_when_vec_already_shorter(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "512"
            vec = list(range(384))  # already shorter than 512
            self.assertEqual(
                kz_embed.maybe_truncate_matryoshka(vec, "mxbai-embed-large"),
                vec,
            )

    def test_garbage_env_falls_back_to_zero(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "not-a-number"
            vec = list(range(1024))
            self.assertEqual(
                kz_embed.maybe_truncate_matryoshka(vec, "mxbai-embed-large"),
                vec,
            )

    def test_negative_clamps_to_zero(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "-100"
            vec = list(range(1024))
            self.assertEqual(
                kz_embed.maybe_truncate_matryoshka(vec, "mxbai-embed-large"),
                vec,
            )

    def test_handles_non_lenable_vec(self):
        """Pathological input that doesn't support len() should pass through."""
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "64"

            class WeirdVec:
                def __getitem__(self, k):
                    return None
            wv = WeirdVec()
            # No exception; returns unchanged
            self.assertIs(
                kz_embed.maybe_truncate_matryoshka(wv, "mxbai-embed-large"),
                wv,
            )

class TestEmbedPathWiring(unittest.TestCase):
    """Source-level check that the matryoshka helpers are actually
    called in the embed pipeline. Source grep — catches a regression
    where someone removes the wiring without removing the helper."""

    EMBED_PATH = PLUGIN_ROOT / "scripts" / "index" / "_embed.py"

    def test_embed_local_calls_maybe_truncate(self):
        text = self.EMBED_PATH.read_text()
        # The single-text path calls maybe_truncate_matryoshka by name
        self.assertIn("maybe_truncate_matryoshka(vec", text,
                      "_embed_local should call maybe_truncate_matryoshka")

    def test_embed_local_batch_consults_matryoshka_dim(self):
        text = self.EMBED_PATH.read_text()
        # The batch path inline-checks dim + family
        self.assertIn("_get_matryoshka_dim()", text)
        self.assertIn("is_matryoshka_model", text)

class TestGetMatryoshkaDim(unittest.TestCase):
    def test_default_zero(self):
        with _EnvSandbox():
            self.assertEqual(kz_embed._get_matryoshka_dim(), 0)

    def test_reads_env(self):
        with _EnvSandbox():
            os.environ["KAIZEN_EMBED_MATRYOSHKA_DIM"] = "256"
            self.assertEqual(kz_embed._get_matryoshka_dim(), 256)

if __name__ == "__main__":
    unittest.main()
