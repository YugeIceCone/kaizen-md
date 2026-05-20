"""Phase 3: symbol_search_mcp returns exact line ranges for code symbols.

Composes Phase 1 (SymbolChunk line ranges) + Phase 2 (onboard schema
line columns). Sandboxed via KAIZEN_ONBOARD_ROOT (so tests never touch
the real repo's onboard.db).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(ROOT / "scripts" / "mcp"))
sys.path.insert(0, str(ROOT / "scripts" / "indexers"))

def _seed_onboard_db(root: Path) -> None:
    """Create a minimal onboard.db with 2 code_files + 3 code_chunks
    that carry line ranges (Phase 2-compatible)."""
    import onboard_index as oi
    (root / ".kaizen").mkdir(parents=True, exist_ok=True)
    conn = oi.open_db(root, create=True)
    # Two source files (code_files has NOT NULL snippet + embedding +
    # sha + updated_at — pass placeholder values).
    conn.execute(
        "INSERT INTO code_files (path, language, bytes, sloc, snippet, "
        "embedding, sha, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/auth.py", "python", 100, 10, "", b"\x00" * 4,
         "abc", "2026-05-19T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO code_files (path, language, bytes, sloc, snippet, "
        "embedding, sha, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src/billing.py", "python", 200, 20, "", b"\x00" * 4,
         "def", "2026-05-19T00:00:00Z"),
    )
    # Embedding: 4-byte zeros (cosine = 0 against any query)
    zeros = b"\x00" * 4
    conn.executescript("""
        INSERT INTO code_chunks (file_id, chunk_idx, char_start, char_end,
            text, embedding, language, kind, symbol_name, line_start, line_end)
        VALUES (1, 0, 0, 50, 'def auth_check(token):\n    return token == "ok"',
            X'00000000', 'python', 'code', 'auth_check', 1, 2);
        INSERT INTO code_chunks (file_id, chunk_idx, char_start, char_end,
            text, embedding, language, kind, symbol_name, line_start, line_end)
        VALUES (1, 1, 60, 120, 'class TokenStore:\n    pass',
            X'00000000', 'python', 'code', 'TokenStore', 5, 6);
        INSERT INTO code_chunks (file_id, chunk_idx, char_start, char_end,
            text, embedding, language, kind, symbol_name, line_start, line_end)
        VALUES (2, 0, 0, 80, 'def billing_total(cart):\n    return sum(cart)',
            X'00000000', 'python', 'code', 'billing_total', 10, 11);
    """)
    conn.commit()
    conn.close()

class TestResolveRoot(unittest.TestCase):

    def test_env_override_wins(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                self.assertEqual(str(ss._resolve_root()), td)

class TestSymbolSearch(unittest.TestCase):

    def _setup(self, td: str) -> None:
        _seed_onboard_db(Path(td))

    def test_returns_line_ranges(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                # No embedding backend in tests → falls back to LIKE
                results = ss.symbol_search("auth", top_k=5)
            self.assertTrue(results)
            first = results[0]
            for key in ("path", "line_start", "line_end", "symbol_name",
                        "language", "kind", "score", "snippet"):
                self.assertIn(key, first)
            self.assertEqual(first["path"], "src/auth.py")
            self.assertEqual(first["line_start"], 1)
            self.assertEqual(first["line_end"], 2)
            self.assertEqual(first["symbol_name"], "auth_check")
            self.assertEqual(first["language"], "python")

    def test_language_filter(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                results = ss.symbol_search("a", top_k=10, language="python")
            # All results python (3 chunks all py-language in fixture)
            for r in results:
                self.assertEqual(r["language"], "python")

    def test_path_glob_filter(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            self._setup(td)
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                results = ss.symbol_search("a", top_k=10,
                                            path_glob="%/billing.py")
            paths = {r["path"] for r in results}
            self.assertEqual(paths, {"src/billing.py"})

    def test_no_db_returns_empty(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            # No db seeded
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                results = ss.symbol_search("anything")
            self.assertEqual(results, [])

class TestSymbolAtLine(unittest.TestCase):

    def test_returns_enclosing_symbol(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            _seed_onboard_db(Path(td))
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                # line 1 in auth.py is inside auth_check (1-2)
                results = ss.symbol_at_line("auth.py", 1)
            self.assertTrue(results)
            self.assertEqual(results[0]["symbol_name"], "auth_check")
            self.assertEqual(results[0]["line_start"], 1)
            self.assertEqual(results[0]["line_end"], 2)

    def test_returns_empty_when_no_enclosing(self):
        try:
            import symbol_search_mcp as ss
        except ImportError:
            self.skipTest("fastmcp not installed")
        with tempfile.TemporaryDirectory() as td:
            _seed_onboard_db(Path(td))
            with patch.dict(os.environ, {"KAIZEN_ONBOARD_ROOT": td}):
                # Line 999 isn't inside any symbol
                results = ss.symbol_at_line("auth.py", 999)
            self.assertEqual(results, [])

if __name__ == "__main__":
    unittest.main()
