"""TDD — discovery_mcp.py — cross-surface federated semantic search.

Sibling-meta of onboard_mcp / knowledge_mcp / claude_docs_mcp /
scrape_mcp. Each per-surface MCP already exists; this aggregator adds
value via ONE call across multiple surfaces (parallel reads, grouped
results, per-surface failure isolation).

Follows the existing kaizen MCP test pattern: verify tool registration
via `mcp._list_tools()`, then test the underlying helpers directly.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/mcp/discovery_mcp.py"


def _load():
    sys.path.insert(0, str(_KZ_DIR / "skills/workflow/scripts"))
    spec = importlib.util.spec_from_file_location("dm_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dm_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestModuleSurface(unittest.TestCase):
    """Module-level invariants — instance, tool registration."""

    def setUp(self):
        self.dm = _load()

    def test_module_exports_mcp_instance(self):
        self.assertTrue(hasattr(self.dm, "mcp"))
        self.assertEqual(self.dm.mcp.name, "discovery")

    def test_three_tools_registered(self):
        tools = asyncio.run(self.dm.mcp._list_tools())
        names = {t.name for t in tools}
        for expected in ("discovery_search", "discovery_stats",
                          "discovery_list_surfaces"):
            self.assertIn(expected, names,
                           f"missing {expected}; got {sorted(names)}")


class TestSurfacesCatalog(unittest.TestCase):
    """The catalog (SURFACES dict) is the SSOT for the 4 indexes."""

    def setUp(self):
        self.dm = _load()

    def test_four_known_surfaces(self):
        self.assertEqual(set(self.dm.SURFACES.keys()),
                          {"codebase", "knowledge", "claude-docs", "scrape"})

    def test_each_surface_has_entry_and_module(self):
        """The catalog's 'slash' field now holds the bin form
        (consolidate-2 D6: per-surface slashes retired into
        /kaizen:discovery). The field name is preserved for back-compat
        with existing consumers; semantic content is the bin name."""
        for name, meta in self.dm.SURFACES.items():
            self.assertIn("slash", meta, f"surface {name} missing slash/entry")
            self.assertTrue(meta["slash"].startswith("kaizen-"),
                            f"surface {name} entry should be a kaizen-* bin "
                            f"post-D6, got {meta['slash']!r}")
            self.assertIn("index_module", meta)
            self.assertIn("desc", meta)


class TestResolvedSurfaces(unittest.TestCase):
    def setUp(self):
        self.dm = _load()

    def test_none_resolves_to_all_four(self):
        self.assertEqual(set(self.dm._resolved_surfaces(None)),
                          {"codebase", "knowledge", "claude-docs", "scrape"})

    def test_empty_list_resolves_to_all_four(self):
        self.assertEqual(set(self.dm._resolved_surfaces([])),
                          {"codebase", "knowledge", "claude-docs", "scrape"})

    def test_explicit_subset_preserved(self):
        self.assertEqual(self.dm._resolved_surfaces(["codebase"]),
                          ["codebase"])

    def test_unknown_surface_passed_through(self):
        """Unknown surfaces flow through; the dispatcher (_do_*_surface)
        is the layer that errors on them so the caller sees the error
        grouped per-surface."""
        self.assertEqual(self.dm._resolved_surfaces(["bogus"]),
                          ["bogus"])


class TestDoSearchSurface(unittest.TestCase):
    """Per-surface dispatcher raises on unknown / propagates on found."""

    def setUp(self):
        self.dm = _load()

    def test_unknown_surface_raises(self):
        with self.assertRaises(ValueError):
            self.dm._do_search_surface("bogus", "q", 5)

    def test_known_surface_imports_index_module(self):
        """Confirms the dispatcher imports + calls do_search on the
        matching module without running real semantic search."""
        class _FakeMod:
            @staticmethod
            def do_search(query, top_k):
                return [{"score": 0.9, "id": 1, "snippet": query}]
        import builtins
        with patch.object(builtins, "__import__", return_value=_FakeMod()):
            result = self.dm._do_search_surface("codebase", "q", 5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["score"], 0.9)


class TestListEmbedModels(unittest.TestCase):
    """`discovery_list_embed_models` surfaces locally-available
    embedding-capable models so the caller can pick one when
    re-indexing or comparing surfaces."""

    def setUp(self):
        self.dm = _load()

    def test_list_embed_models_tool_registered(self):
        tools = asyncio.run(self.dm.mcp._list_tools())
        names = {t.name for t in tools}
        self.assertIn("discovery_list_embed_models", names)

    def test_helper_filters_ollama_models_by_capability(self):
        """The helper queries Ollama and keeps only models whose
        capabilities include 'embedding'."""
        fake_models = [
            {"name": "qwen3-embedding:0.6b",
             "capabilities": ["embedding"], "dim": 1024},
            {"name": "qwen2.5-coder:1.5b",
             "capabilities": ["completion"], "dim": None},
            {"name": "nomic-embed-text",
             "capabilities": ["embedding"], "dim": 768},
        ]
        with patch.object(self.dm, "_fetch_ollama_models_with_caps",
                           return_value=fake_models):
            result = self.dm._list_available_embed_models()
        names = {m["name"] for m in result}
        self.assertIn("qwen3-embedding:0.6b", names)
        self.assertIn("nomic-embed-text", names)
        self.assertNotIn("qwen2.5-coder:1.5b", names)

    def test_helper_returns_empty_on_ollama_unavailable(self):
        """No Ollama connection → return []; tool degrades gracefully."""
        with patch.object(self.dm, "_fetch_ollama_models_with_caps",
                           side_effect=ConnectionError("ollama down")):
            result = self.dm._list_available_embed_models()
        self.assertEqual(result, [])


class TestFederatedSearchAggregator(unittest.IsolatedAsyncioTestCase):
    """The async aggregator that's exposed as discovery_search MCP tool.

    Pulled out as a helper to avoid the @mcp.tool wrapper indirection."""

    def setUp(self):
        self.dm = _load()

    async def _call_aggregator(self, query: str,
                                  surfaces: list[str] | None = None,
                                  top_k_per: int = 4) -> dict:
        """Replicate what discovery_search.fn would do — the same body
        runs whether invoked via MCP or directly. We test the body."""
        import asyncio as _a
        picked = self.dm._resolved_surfaces(surfaces)
        def _run(name: str):
            try:
                return name, self.dm._do_search_surface(name, query, top_k_per)
            except Exception as exc:  # noqa: BLE001
                return name, {"error": str(exc)}
        results = await _a.gather(
            *(_a.to_thread(_run, n) for n in picked)
        )
        return {name: r for name, r in results}

    async def test_default_hits_all_four(self):
        with patch.object(self.dm, "_do_search_surface",
                           return_value=[{"score": 0.5}]):
            result = await self._call_aggregator("q")
        self.assertEqual(set(result.keys()),
                          {"codebase", "knowledge", "claude-docs", "scrape"})

    async def test_explicit_subset(self):
        with patch.object(self.dm, "_do_search_surface",
                           return_value=[]):
            result = await self._call_aggregator(
                "q", surfaces=["codebase", "knowledge"])
        self.assertEqual(set(result.keys()), {"codebase", "knowledge"})

    async def test_per_surface_failure_isolated(self):
        def fake_search(surface, q, k):
            if surface == "claude-docs":
                raise RuntimeError("ollama unavailable")
            return [{"score": 0.9, "snippet": surface}]
        with patch.object(self.dm, "_do_search_surface",
                           side_effect=fake_search):
            result = await self._call_aggregator("q")
        self.assertIsInstance(result["codebase"], list)
        self.assertIsInstance(result["claude-docs"], dict)
        self.assertIn("error", result["claude-docs"])
        self.assertIn("ollama", result["claude-docs"]["error"].lower())

    async def test_unknown_surface_returns_error_dict(self):
        result = await self._call_aggregator("q", surfaces=["nonexistent"])
        self.assertIn("nonexistent", result)
        self.assertIn("error", result["nonexistent"])


if __name__ == "__main__":
    unittest.main()
