#!/usr/bin/env python3
"""Unit tests for _embed.py — stale HTTP-cache fallback (v1.25.3+).

Reproducer this guards against: cached endpoint at
~/.claude/.kaizen/embed_endpoint.json points at a llama-server that
has since died. resolve_backend() returns the cached config; the
HTTP embed call raises URLError. Before v1.25.3 that error escaped
to the indexer caller. After: embed_one / embed_batch catch it,
invalidate the cache, re-resolve, and fall back to local.

Run:
    python3 -m unittest tests.test_embed -v
"""

from __future__ import annotations

import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "kaizen" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import _embed  # noqa: E402


class TestStaleHttpCacheFallback(unittest.TestCase):
    """When the cached HTTP endpoint dies, embed_one/embed_batch must
    invalidate the cache and route to the local backend instead of
    bubbling URLError to the caller."""

    def tearDown(self) -> None:
        _embed._cached_cfg = None

    def test_embed_one_falls_back_to_local_when_http_unreachable(self) -> None:
        url_error = urllib.error.URLError("Connection refused")
        local_result = (b"local-bytes", 384)
        backends = [
            {"kind": "http", "base_url": "http://dead.local/v1", "model": "dead"},
            {"kind": "local", "model": "MiniLM", "dim": 384},
        ]
        with patch.object(_embed, "_embed_http", side_effect=url_error) as http_mock, \
             patch.object(_embed, "_embed_local", return_value=local_result) as local_mock, \
             patch.object(_embed, "resolve_backend", side_effect=backends):
            result = _embed.embed_one("hello")
        self.assertEqual(result, local_result)
        http_mock.assert_called_once()
        local_mock.assert_called_once()

    def test_embed_batch_falls_back_to_local_when_http_unreachable(self) -> None:
        url_error = urllib.error.URLError("Connection refused")
        local_result = ([b"a", b"b"], 384)
        backends = [
            {"kind": "http", "base_url": "http://dead.local/v1", "model": "dead"},
            {"kind": "local", "model": "MiniLM", "dim": 384},
        ]
        with patch.object(_embed, "_embed_http_batch", side_effect=url_error) as http_mock, \
             patch.object(_embed, "_embed_local_batch", return_value=local_result) as local_mock, \
             patch.object(_embed, "resolve_backend", side_effect=backends):
            result = _embed.embed_batch(["x", "y"])
        self.assertEqual(result, local_result)
        http_mock.assert_called_once()
        local_mock.assert_called_once()

    def test_embed_one_retries_http_when_refresh_finds_new_endpoint(self) -> None:
        """If the live re-probe finds a different live HTTP endpoint,
        embed_one retries against it instead of falling to local."""
        url_error = urllib.error.URLError("Connection refused")
        http_result = (b"http-bytes-2", 768)
        backends = [
            {"kind": "http", "base_url": "http://dead.local/v1", "model": "dead"},
            {"kind": "http", "base_url": "http://alive.local/v1", "model": "alive"},
        ]
        # First _embed_http call raises (dead endpoint). Second succeeds.
        with patch.object(_embed, "_embed_http", side_effect=[url_error, http_result]) as http_mock, \
             patch.object(_embed, "_embed_local") as local_mock, \
             patch.object(_embed, "resolve_backend", side_effect=backends):
            result = _embed.embed_one("hello")
        self.assertEqual(result, http_result)
        self.assertEqual(http_mock.call_count, 2)
        local_mock.assert_not_called()

    def test_embed_batch_empty_input_short_circuits(self) -> None:
        # Empty input never touches a backend.
        with patch.object(_embed, "_embed_http_batch") as http_mock, \
             patch.object(_embed, "_embed_local_batch") as local_mock, \
             patch.object(_embed, "resolve_backend") as resolve_mock:
            blobs, dim = _embed.embed_batch([])
        self.assertEqual(blobs, [])
        self.assertEqual(dim, 0)
        resolve_mock.assert_not_called()
        http_mock.assert_not_called()
        local_mock.assert_not_called()


class TestInvalidateCache(unittest.TestCase):
    def test_clears_in_memory_state(self) -> None:
        _embed._cached_cfg = {"kind": "http", "base_url": "x", "model": "y"}
        _embed._invalidate_cache()
        self.assertIsNone(_embed._cached_cfg)


class TestIsEmbeddingModelName(unittest.TestCase):
    """Spot-check the heuristic that distinguishes embed-shaped names
    from chat-shaped names — keeps the resolver from picking a chat
    model as an embed backend."""

    def test_embedding_names_match(self) -> None:
        for name in [
            "nomic-embed-text-v2-moe",
            "bge-base-en-v1.5",
            "gte-large",
            "all-MiniLM-L6-v2",
            "text-embedding-3-small",
            "stella-en-400M-v5",
            "jina-embed-v3",
            "e5-large-v2",
            "qwen3-coder-embed",
        ]:
            self.assertTrue(_embed.is_embedding_model_name(name), f"missed: {name}")

    def test_chat_names_do_not_match(self) -> None:
        for name in [
            "qwen3-30b-a3b-instruct",
            "llama-3.1-8b",
            "mixtral-8x7b",
            "claude-opus-4-7",
        ]:
            self.assertFalse(_embed.is_embedding_model_name(name), f"false positive: {name}")


if __name__ == "__main__":
    unittest.main()
