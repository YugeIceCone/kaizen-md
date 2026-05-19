"""Integration tests for O2 + O6 + M7 — AST chunking + xref + symbol-search MCP.

Covers the full path: chunk_record routes Python through the ast chunker
+ emits `symbol_name`, schema migrations add the columns, INSERT path
persists them, xref imports populate the new table, and the M7 MCP
tools (onboard_symbol_search + onboard_xref) return the right rows.

Run:
    python3 -m unittest tests.test_onboard_o2_o6_m7 -v
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "indexers"))

import onboard_index as oi  # noqa: E402


# ─── Schema migration ───────────────────────────────────────────────


class TestSymbolNameMigration(unittest.TestCase):
    def test_new_db_has_symbol_name_column(self):
        with tempfile.TemporaryDirectory() as td:
            conn = oi.open_db(Path(td), create=True)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("symbol_name", cols)
            conn.close()

    def test_idx_chunk_symbol_index_exists(self):
        with tempfile.TemporaryDirectory() as td:
            conn = oi.open_db(Path(td), create=True)
            idx = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_chunk_symbol'"
            ).fetchone()
            self.assertIsNotNone(idx)
            conn.close()

    def test_pre_v133_db_gets_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            db = oi.db_path(tmp)
            db.parent.mkdir(parents=True, exist_ok=True)
            # Build a pre-v1.33 schema (post-v1.32: has `kind` but no `symbol_name`)
            conn = sqlite3.connect(str(db))
            conn.executescript("""
                CREATE TABLE code_files (
                    id INTEGER PRIMARY KEY, path TEXT, language TEXT,
                    bytes INTEGER, sloc INTEGER, snippet TEXT,
                    embedding BLOB, sha TEXT, updated_at TEXT);
                CREATE TABLE code_chunks (
                    id INTEGER PRIMARY KEY, file_id INTEGER,
                    chunk_idx INTEGER, char_start INTEGER, char_end INTEGER,
                    text TEXT, embedding BLOB, language TEXT,
                    kind TEXT DEFAULT 'code');
            """)
            conn.commit()
            cols_before = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertNotIn("symbol_name", cols_before)
            conn.close()
            # Reopen via the indexer's open_db → migration runs
            conn = oi.open_db(tmp, create=True)
            cols_after = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("symbol_name", cols_after)
            conn.close()


class TestXrefTable(unittest.TestCase):
    def test_xref_table_exists(self):
        with tempfile.TemporaryDirectory() as td:
            conn = oi.open_db(Path(td), create=True)
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='code_chunks_xref'"
            ).fetchone()
            self.assertIsNotNone(row)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks_xref)")}
            self.assertEqual(
                cols,
                {"id", "chunk_id", "symbol", "kind"},
            )
            conn.close()


# ─── chunk_record routes Python through ast chunker ─────────────────


class TestChunkRecordAstRouting(unittest.TestCase):
    def _make(self, language: str, source: str):
        return {
            "path": "t.py" if language == "python" else "t.rs",
            "language": language,
            "sha": "abc",
            "text": source,
            "cleaned": source,  # for simplicity; real flow runs strip_comments
            "docstrings": "",
        }

    def test_python_uses_ast_chunker(self):
        src = (
            "import os\n\n"
            "def foo():\n    return 1\n\n"
            "class Bar:\n    def baz(self):\n        pass\n"
        )
        rec = self._make("python", src)
        chunks = oi.chunk_record(rec)
        kept = [c for c in chunks if c.get("kept")]
        # AST chunker emits one chunk per symbol — at least 3 here
        # (module prologue + foo + Bar)
        symbol_names = [c.get("symbol_name", "") for c in kept]
        self.assertIn("<module>", symbol_names)
        self.assertIn("foo", symbol_names)
        self.assertIn("Bar", symbol_names)

    def test_non_python_uses_generic_chunker(self):
        rec = self._make("rust", "fn foo() {}\n")
        chunks = oi.chunk_record(rec)
        kept = [c for c in chunks if c.get("kept")]
        # Generic chunker → symbol_name is empty
        self.assertTrue(kept)
        for c in kept:
            self.assertEqual(c.get("symbol_name", ""), "")

    def test_python_with_syntax_error_falls_back(self):
        # Broken Python → ast chunker returns [] → generic fallback
        rec = self._make("python", "def broken((( :\n")
        chunks = oi.chunk_record(rec)
        kept = [c for c in chunks if c.get("kept")]
        # Should still produce SOMETHING (generic chunker on the source)
        # with empty symbol_name
        if kept:
            for c in kept:
                self.assertEqual(c.get("symbol_name", ""), "")


# ─── _populate_xref_imports ─────────────────────────────────────────


class TestPopulateXrefImports(unittest.TestCase):
    def test_python_imports_get_xref_rows(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            conn = oi.open_db(tmp, create=True)
            # Pretend a file_id 1 with one chunk at idx 0 (module-level)
            conn.execute(
                "INSERT INTO code_files (id, path, language, bytes, sloc, "
                "snippet, embedding, sha, updated_at) "
                "VALUES (1, 'm.py', 'python', 100, 5, '', X'00', 'sha', '')"
            )
            conn.execute(
                "INSERT INTO code_chunks (file_id, chunk_idx, char_start, "
                "char_end, text, embedding, language, kind, symbol_name) "
                "VALUES (1, 0, 0, 100, 'import os\\nimport sys', X'00', "
                "'python', 'code', '<module>')"
            )
            conn.commit()
            cleaned = {
                "language": "python",
                "text": "import os\nimport sys\nfrom pathlib import Path\n",
                "cleaned": "",
            }
            kept = [{"chunk_idx": 0, "symbol_name": "<module>"}]
            oi._populate_xref_imports(conn, 1, cleaned, kept)
            rows = conn.execute(
                "SELECT symbol, kind FROM code_chunks_xref"
            ).fetchall()
            symbols = {r["symbol"] for r in rows}
            self.assertEqual(symbols, {"os", "sys", "Path"})
            self.assertTrue(all(r["kind"] == "import" for r in rows))
            conn.close()

    def test_non_python_skips(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            conn = oi.open_db(tmp, create=True)
            cleaned = {"language": "rust", "text": "use serde;", "cleaned": ""}
            oi._populate_xref_imports(conn, 1, cleaned, [])
            count = conn.execute(
                "SELECT COUNT(*) FROM code_chunks_xref"
            ).fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()

    def test_no_kept_chunks_skips(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            conn = oi.open_db(tmp, create=True)
            cleaned = {"language": "python", "text": "import os\n", "cleaned": ""}
            oi._populate_xref_imports(conn, 1, cleaned, [])
            count = conn.execute(
                "SELECT COUNT(*) FROM code_chunks_xref"
            ).fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()


# ─── M7 MCP tools ────────────────────────────────────────────────────


class _CwdMixin:
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmpcm = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpcm.name)
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmpcm.cleanup()


class TestOnboardMcpSymbolSearch(_CwdMixin, unittest.TestCase):
    def _import(self):
        # Force reload so cwd resolution is fresh
        for m in ("onboard_mcp", "onboard_index"):
            if m in sys.modules:
                del sys.modules[m]
        import onboard_mcp
        return onboard_mcp

    def _seed_chunks(self):
        import onboard_index as oi_
        conn = oi_.open_db(self.tmp, create=True)
        conn.execute(
            "INSERT INTO code_files (id, path, language, bytes, sloc, "
            "snippet, embedding, sha, updated_at) "
            "VALUES (1, 's.py', 'python', 100, 5, '', X'00', 'sha', '')"
        )
        conn.executemany(
            "INSERT INTO code_chunks (file_id, chunk_idx, char_start, char_end, "
            "text, embedding, language, kind, symbol_name) VALUES (?, ?, ?, ?, "
            "?, ?, ?, ?, ?)",
            [
                (1, 0, 0, 50, "import os", b"\x00", "python", "code", "<module>"),
                (1, 1, 50, 100, "def carve(): pass", b"\x00", "python", "code", "carve"),
                (1, 2, 100, 200, "class Foo: pass", b"\x00", "python", "code", "Foo"),
            ],
        )
        conn.commit()
        conn.close()

    def test_empty_name_lists_all_ast_chunks(self):
        self._seed_chunks()
        m = self._import()
        out = asyncio.run(m.onboard_symbol_search(""))
        names = {r["symbol_name"] for r in out}
        # All three seeded symbols
        self.assertEqual(names, {"<module>", "carve", "Foo"})

    def test_name_filter_substring(self):
        self._seed_chunks()
        m = self._import()
        out = asyncio.run(m.onboard_symbol_search("carv"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol_name"], "carve")

    def test_glob_match(self):
        self._seed_chunks()
        m = self._import()
        # 'F*' should match 'Foo'
        out = asyncio.run(m.onboard_symbol_search("F*"))
        names = {r["symbol_name"] for r in out}
        self.assertIn("Foo", names)


class TestOnboardMcpXref(_CwdMixin, unittest.TestCase):
    def _import(self):
        for m in ("onboard_mcp", "onboard_index"):
            if m in sys.modules:
                del sys.modules[m]
        import onboard_mcp
        return onboard_mcp

    def _seed(self):
        import onboard_index as oi_
        conn = oi_.open_db(self.tmp, create=True)
        conn.execute(
            "INSERT INTO code_files (id, path, language, bytes, sloc, "
            "snippet, embedding, sha, updated_at) "
            "VALUES (1, 's.py', 'python', 100, 5, '', X'00', 'sha', '')"
        )
        conn.execute(
            "INSERT INTO code_chunks (id, file_id, chunk_idx, char_start, "
            "char_end, text, embedding, language, kind, symbol_name) "
            "VALUES (10, 1, 0, 0, 50, 'import os', X'00', 'python', 'code', "
            "'<module>')"
        )
        conn.executemany(
            "INSERT INTO code_chunks_xref (chunk_id, symbol, kind) VALUES (?, ?, ?)",
            [(10, "os", "import"),
             (10, "pathlib.Path", "import"),
             (10, "requests", "import")],
        )
        conn.commit()
        conn.close()

    def test_xref_finds_imports(self):
        self._seed()
        m = self._import()
        out = asyncio.run(m.onboard_xref("os"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "os")
        self.assertEqual(out[0]["kind"], "import")
        self.assertEqual(out[0]["path"], "s.py")

    def test_xref_substring_match(self):
        self._seed()
        m = self._import()
        out = asyncio.run(m.onboard_xref("path"))
        symbols = {r["symbol"] for r in out}
        self.assertIn("pathlib.Path", symbols)

    def test_xref_no_index(self):
        m = self._import()
        out = asyncio.run(m.onboard_xref("anything"))
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
