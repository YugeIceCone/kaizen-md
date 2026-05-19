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


if __name__ == "__main__":
    unittest.main()
