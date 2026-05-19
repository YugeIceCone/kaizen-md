"""Tests for webfetch_mcp.py — recall + dedup + search + policy.

Composes with the PostToolUse capture hook (test_webfetch_capture_hook.py);
this tests the QUERY side: given a populated jsonl, the MCP tools
return the right answers.

Sandbox: KAIZEN_WEBFETCH_CAPTURE_LOG redirects the source jsonl.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "mcp"))


def _iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_entries(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestCached(unittest.TestCase):
    """webfetch_cached recalls fetches within TTL."""

    def test_no_file_returns_miss(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed in this env")
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_cached("http://x/", "p", ttl_min=60)
        self.assertEqual(r, {"hit": False})

    def test_recent_match_within_ttl_returns_hit(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now - dt.timedelta(minutes=5)),
                "session_id": "s1",
                "url": "http://x/", "prompt": "p",
                "response": "BODY-A",
            }])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_cached("http://x/", "p", ttl_min=60)
        self.assertTrue(r["hit"])
        self.assertEqual(r["body"], "BODY-A")
        self.assertEqual(r["session_id"], "s1")

    def test_expired_match_returns_miss(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now - dt.timedelta(minutes=120)),
                "session_id": "s1",
                "url": "http://x/", "prompt": "p",
                "response": "OLD",
            }])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_cached("http://x/", "p", ttl_min=60)
        self.assertEqual(r, {"hit": False})

    def test_different_prompt_returns_miss(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now), "session_id": "s1",
                "url": "http://x/", "prompt": "different",
                "response": "B",
            }])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_cached("http://x/", "p", ttl_min=60)
        self.assertEqual(r["hit"], False)


class TestSessionSeen(unittest.TestCase):
    """webfetch_session_seen tracks per-session re-reads."""

    def test_same_session_match(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now), "session_id": "session-A",
                "url": "http://x/", "prompt": "p",
                "response": "B",
            }])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_session_seen("http://x/", "p", "session-A")
        self.assertTrue(r["seen"])

    def test_different_session_returns_not_seen(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now), "session_id": "session-A",
                "url": "http://x/", "prompt": "p",
                "response": "B",
            }])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_session_seen("http://x/", "p", "session-B")
        self.assertFalse(r["seen"])

    def test_missing_session_id_returns_reason(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        r = wf.webfetch_session_seen("http://x/", "p", "")
        self.assertFalse(r["seen"])
        self.assertIn("reason", r)


class TestSearch(unittest.TestCase):

    def test_substring_match_returns_hits(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [
                {"ts": _iso(now), "url": "u1", "prompt": "p1",
                 "response": "talks about hooks and observability"},
                {"ts": _iso(now), "url": "u2", "prompt": "p2",
                 "response": "unrelated"},
                {"ts": _iso(now), "url": "u3", "prompt": "hooks reference",
                 "response": "something else"},
            ])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_search("hooks", top_k=5)
        urls = [m["url"] for m in r["matches"]]
        self.assertIn("u1", urls)
        self.assertIn("u3", urls)
        self.assertNotIn("u2", urls)

    def test_top_k_caps_results(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [
                {"ts": _iso(now), "url": f"u{i}", "prompt": "p",
                 "response": "needle in stack"}
                for i in range(10)
            ])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_search("needle", top_k=3)
        self.assertEqual(len(r["matches"]), 3)


class TestPolicy(unittest.TestCase):

    def test_default_allows(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        env_copy = {k: v for k, v in os.environ.items()
                    if k not in ("KAIZEN_WEBFETCH_DENY_DOMAINS",
                                 "KAIZEN_WEBFETCH_RATE_LIMIT_PER_MIN")}
        with patch.dict(os.environ, env_copy, clear=True):
            r = wf.webfetch_policy("https://example.com/foo")
        self.assertEqual(r["verdict"], "allow")

    def test_deny_list_blocks(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        with patch.dict(os.environ,
                        {"KAIZEN_WEBFETCH_DENY_DOMAINS": "internal.local,foo.com"}):
            r = wf.webfetch_policy("https://foo.com/x")
        self.assertEqual(r["verdict"], "deny")
        self.assertIn("foo.com", r["reason"])

    def test_rate_limit_triggers_when_cap_exceeded(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [
                {"ts": _iso(now - dt.timedelta(seconds=10)),
                 "url": f"https://example.com/{i}",
                 "prompt": "p", "response": ""}
                for i in range(5)
            ])
            env_copy = {k: v for k, v in os.environ.items()
                        if k not in ("KAIZEN_WEBFETCH_DENY_DOMAINS",)}
            env_copy.update({
                "KAIZEN_WEBFETCH_CAPTURE_LOG": str(log),
                "KAIZEN_WEBFETCH_RATE_LIMIT_PER_MIN": "3",
            })
            with patch.dict(os.environ, env_copy, clear=True):
                r = wf.webfetch_policy("https://example.com/new")
        self.assertEqual(r["verdict"], "rate-limited")


class TestWebfetchStore(unittest.TestCase):
    """webfetch_store fetches via stdlib + stores body — agent gets only
    metadata (zero-token storage)."""

    def test_blocked_by_policy_returns_error(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        with patch.dict(os.environ,
                        {"KAIZEN_WEBFETCH_DENY_DOMAINS": "foo.com"}):
            r = wf.webfetch_store("https://foo.com/x")
        self.assertFalse(r["stored"])
        self.assertIn("policy", r["error"])

    def test_successful_store_returns_metadata_only(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        body_bytes = b"Hello world from a test response. " * 50

        class _FakeResp:
            def __init__(self, payload): self._p = payload
            def read(self, n=None): return self._p if n is None else self._p[:n]
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            env_copy = {k: v for k, v in os.environ.items()
                        if k not in ("KAIZEN_WEBFETCH_DENY_DOMAINS",
                                     "KAIZEN_WEBFETCH_RATE_LIMIT_PER_MIN")}
            env_copy["KAIZEN_WEBFETCH_CAPTURE_LOG"] = str(log)
            with patch.dict(os.environ, env_copy, clear=True), \
                 patch("urllib.request.urlopen", return_value=_FakeResp(body_bytes)):
                r = wf.webfetch_store("https://example.com/x",
                                       prompt="check it",
                                       max_bytes=10000)

            # Metadata returned, body NOT in the response (token-free)
            self.assertTrue(r["stored"])
            self.assertEqual(r["url"], "https://example.com/x")
            self.assertIn("size_bytes", r)
            self.assertIn("sha256", r)
            self.assertIn("ts", r)
            self.assertNotIn("body", r)
            self.assertNotIn("response", r)

            # The stored line carries the body for later recall
            stored = json.loads(log.read_text().strip())
            self.assertIn("Hello world", stored["response"])
            self.assertEqual(stored["url"], "https://example.com/x")

    def test_truncates_oversized_body(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        big = b"x" * 50_000

        class _FakeResp:
            def __init__(self, p): self._p = p
            def read(self, n=None): return self._p if n is None else self._p[:n]
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}), \
                 patch("urllib.request.urlopen", return_value=_FakeResp(big)):
                r = wf.webfetch_store("https://example.com/big", max_bytes=1000)
            self.assertTrue(r["stored"])
            self.assertTrue(r["truncated"])
            stored = json.loads(log.read_text().strip())
            self.assertIn("truncated at 1000B", stored["response"])

    def test_http_error_returns_error_field(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("dns dead")):
            r = wf.webfetch_store("https://nonexistent.invalid/")
        self.assertFalse(r["stored"])
        self.assertIn("URLError", r["error"])


class TestWebfetchSemsearch(unittest.TestCase):
    """webfetch_semsearch returns snippets-only (never full bodies).
    Falls back to substring when embedding unavailable."""

    def test_empty_query_returns_noop(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        r = wf.webfetch_semsearch("", top_k=5)
        self.assertEqual(r["matches"], [])
        self.assertEqual(r["method"], "noop")

    def test_empty_store_returns_noop(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                r = wf.webfetch_semsearch("query", top_k=5)
        self.assertEqual(r["matches"], [])
        self.assertEqual(r["method"], "noop")

    def test_falls_back_to_substring_when_embed_unavailable(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now), "url": "u", "prompt": "p",
                "response": "needle hidden in haystack",
            }])
            # Patch _embed.embed_one to raise → falls back to substring
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                import _embed
                with patch.object(_embed, "embed_one",
                                  side_effect=RuntimeError("no embed backend")):
                    r = wf.webfetch_semsearch("needle", top_k=5)
        self.assertEqual(r["method"], "fallback-substring")
        # Fallback still returns the match
        urls = [m["url"] for m in r["matches"]]
        self.assertIn("u", urls)

    def test_returns_snippets_not_full_bodies(self):
        try:
            import webfetch_mcp as wf
        except ImportError:
            self.skipTest("fastmcp not installed")
        long_body = "needle " + ("filler " * 1000)
        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "wf.jsonl"
            _seed_entries(log, [{
                "ts": _iso(now), "url": "u", "prompt": "p",
                "response": long_body,
            }])
            with patch.dict(os.environ,
                            {"KAIZEN_WEBFETCH_CAPTURE_LOG": str(log)}):
                # Force the embed call to fail → semsearch falls back to substring.
                import _embed
                with patch.object(_embed, "embed_one",
                                  side_effect=RuntimeError("no embed backend")):
                    r = wf.webfetch_semsearch("needle", top_k=1,
                                                snippet_width=300)
        self.assertTrue(r["matches"])
        snippet = r["matches"][0]["snippet"]
        # NEVER the full 7KB body — bounded snippet only
        self.assertLessEqual(len(snippet), 350)
        self.assertIn("needle", snippet)


if __name__ == "__main__":
    unittest.main()
