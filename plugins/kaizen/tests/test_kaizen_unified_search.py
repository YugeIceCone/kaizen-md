"""Phase 4.B: unified `kaizen_search` MCP tool with auto-corpus routing.

Sibling to `discovery_search` (existing federated 4-surface tool).
Adds:
- Auto-routing by query shape (e.g. `def foo` → symbol-search,
  `pref-X` → brain, `error: rate limit` → trace).
- `corpus="all"` fan-out across all 7 kaizen indexes.
- Explicit `corpus=<name>` direct pass-through to a single index.

Sandboxed via env knobs for each backing surface.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(ROOT / "scripts" / "mcp"))

class TestAutoCorpusRouting(unittest.TestCase):
    """`pick_corpus(query) → corpus_name` is the pure routing layer."""

    def test_def_pattern_routes_to_symbol_search(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("def auth_check"), "symbol-search")
        self.assertEqual(dm.pick_corpus("class TokenStore"), "symbol-search")
        self.assertEqual(dm.pick_corpus("function takes a Path"), "symbol-search")

    def test_pref_pattern_routes_to_brain(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("pref-no-deletions"), "brain")
        self.assertEqual(dm.pick_corpus("Notes/pref-tdd"), "brain")

    def test_error_pattern_routes_to_trace(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("error: timeout"), "trace")
        self.assertEqual(dm.pick_corpus("Exception in tick"), "trace")

    def test_https_url_pattern_routes_to_scrape(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("https://docs.anthropic.com"),
                          "scrape")

    def test_doc_keywords_route_to_claude_docs(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("anthropic API docs"),
                          "claude-docs")
        self.assertEqual(dm.pick_corpus("Claude Code memory"),
                          "claude-docs")

    def test_no_match_falls_through_to_all(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("random unmatched query"), "all")

class TestKaizenSearchEntry(unittest.TestCase):
    """The kaizen_search MCP tool delegates by corpus."""

    def test_explicit_corpus_routes_directly(self):
        """When corpus is explicit, no auto-routing."""
        try:
            import discovery_mcp as dm
        except ImportError:
            self.skipTest("fastmcp not installed")
        # When `corpus` is a single name we resolve to one surface
        # and skip the auto-router.
        self.assertEqual(dm.pick_corpus("anything", "brain"), "brain")
        self.assertEqual(dm.pick_corpus("anything", "symbol-search"),
                          "symbol-search")

    def test_auto_uses_pattern_router(self):
        import discovery_mcp as dm
        # auto explicit
        self.assertEqual(dm.pick_corpus("def foo", "auto"), "symbol-search")

    def test_all_keyword_signals_fanout(self):
        import discovery_mcp as dm
        self.assertEqual(dm.pick_corpus("any", "all"), "all")

if __name__ == "__main__":
    unittest.main()
