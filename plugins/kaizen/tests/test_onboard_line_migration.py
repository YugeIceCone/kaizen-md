"""Phase 2: onboard code_chunks gains line_start + line_end columns.

Idempotent migration adds the columns to pre-existing dbs; fresh dbs
get them from SCHEMA_SQL. Insert path populates them from
_ast_chunk.SymbolChunk for Python (non-AST chunks default to 0).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "indexers"))


class TestSchemaHasLineColumns(unittest.TestCase):

    def test_fresh_db_has_line_columns(self):
        import onboard_index as oi
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".kaizen").mkdir()
            conn = oi.open_db(Path(td), create=True)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("line_start", cols)
            self.assertIn("line_end", cols)

    def test_migration_is_idempotent(self):
        """Re-running open_db twice on the same path doesn't fail."""
        import onboard_index as oi
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".kaizen").mkdir()
            conn1 = oi.open_db(Path(td), create=True)
            conn1.close()
            conn2 = oi.open_db(Path(td), create=True)
            cols = {row[1] for row in conn2.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("line_start", cols)

    def test_migration_helper_is_idempotent_on_real_schema(self):
        """Direct call to _migrate_line_columns on a real db is a no-op
        when columns already exist."""
        import onboard_index as oi
        import onboard_schema as os_schema
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".kaizen").mkdir()
            conn = oi.open_db(Path(td), create=True)
            # Columns present after fresh open
            cols_before = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("line_start", cols_before)
            # Re-running the migration is a no-op (no OperationalError)
            os_schema._migrate_line_columns(conn)
            cols_after = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertEqual(cols_before, cols_after)


class TestInsertPathPopulatesLines(unittest.TestCase):
    """When the indexer writes a Python file's chunks, the line columns
    carry the values from _ast_chunk.SymbolChunk."""

    def test_python_file_chunks_carry_line_ranges(self):
        """We can't run do_index without an embedding backend, so this
        test asserts the chunker → dict shape preserves line_start/end."""
        import _ast_chunk as ac
        src = 'def foo():\n    return 1\n\nclass Bar:\n    pass\n'
        chunks = ac.chunk_python_by_symbol(src)
        # Each chunk now has non-zero line ranges
        for c in chunks:
            self.assertGreater(c.line_start, 0,
                f"chunk {c.symbol_name!r} missing line_start")
            self.assertGreaterEqual(c.line_end, c.line_start)


if __name__ == "__main__":
    unittest.main()
