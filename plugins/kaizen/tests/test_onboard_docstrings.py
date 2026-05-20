"""Tests for O1 — preserve docstrings as a sidecar signal.

`extract_docstrings(source, language)` pulls docstrings/header-comments
per language. `clean_for_embed` stores them on the cleaned record.
`chunk_record` emits doc-chunks alongside code-chunks with kind="doc".
`open_db` migrates pre-v1.32 dbs to add the `kind` column.

Run:
    python3 -m unittest tests.test_onboard_docstrings -v
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _kaizen_paths  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "indexers"))

import onboard_index as oi  # noqa: E402

# ─── extract_docstrings ──────────────────────────────────────────────

class TestExtractPythonDocstrings(unittest.TestCase):
    def test_extracts_module_docstring(self):
        src = '"""Top-level module doc.\n\nMore detail here."""\n\ndef foo(): pass\n'
        out = oi.extract_docstrings(src, "python")
        self.assertIn("Top-level module doc.", out)
        self.assertIn("More detail here.", out)

    def test_extracts_function_docstrings(self):
        src = 'def foo():\n    """foo does the thing."""\n    return 1\n'
        out = oi.extract_docstrings(src, "python")
        self.assertIn("foo does the thing.", out)

    def test_extracts_class_docstrings(self):
        src = 'class Foo:\n    """Foo represents X."""\n    pass\n'
        out = oi.extract_docstrings(src, "python")
        self.assertIn("Foo represents X.", out)

    def test_empty_on_no_docstrings(self):
        src = "def foo():\n    return 1\n"
        out = oi.extract_docstrings(src, "python")
        self.assertEqual(out, "")

    def test_falls_back_to_regex_on_syntax_error(self):
        # Malformed Python but contains a triple-quoted string — regex
        # fallback should still extract it.
        src = '"""this is a doc"""\ndef broken((( :\n'
        out = oi.extract_docstrings(src, "python")
        self.assertIn("this is a doc", out)

class TestExtractRustDocstrings(unittest.TestCase):
    def test_extracts_outer_doc_lines(self):
        src = "/// Top-level fn docs.\n/// More detail.\nfn foo() {}\n"
        out = oi.extract_docstrings(src, "rust")
        self.assertIn("Top-level fn docs.", out)
        self.assertIn("More detail.", out)

    def test_extracts_inner_doc_lines(self):
        src = "//! Module-level doc.\n\nfn foo() {}\n"
        out = oi.extract_docstrings(src, "rust")
        self.assertIn("Module-level doc.", out)

    def test_strips_leading_slash_prefix(self):
        src = "/// hello world\n"
        out = oi.extract_docstrings(src, "rust")
        self.assertEqual(out.strip(), "hello world")

    def test_ignores_regular_comments(self):
        src = "// not a doc\nfn foo() {}\n"
        out = oi.extract_docstrings(src, "rust")
        self.assertEqual(out, "")

class TestExtractJSDoc(unittest.TestCase):
    def test_extracts_jsdoc_block(self):
        src = "/**\n * computes the sum.\n * @param a number\n */\nfunction sum(a) {}\n"
        out = oi.extract_docstrings(src, "typescript")
        self.assertIn("computes the sum.", out)
        self.assertIn("@param a number", out)

    def test_strips_leading_stars(self):
        src = "/**\n * line one\n * line two\n */\n"
        out = oi.extract_docstrings(src, "javascript")
        self.assertNotIn("*", out.replace("@param", ""))  # leading * gone
        self.assertIn("line one", out)
        self.assertIn("line two", out)

    def test_ignores_regular_block_comment(self):
        src = "/* not a doc */ const x = 1;\n"
        out = oi.extract_docstrings(src, "typescript")
        self.assertEqual(out, "")

class TestExtractDocstringsFallback(unittest.TestCase):
    def test_returns_empty_for_unsupported_language(self):
        out = oi.extract_docstrings("# a yaml comment\nkey: val\n", "yaml")
        self.assertEqual(out, "")

    def test_returns_empty_on_empty_source(self):
        self.assertEqual(oi.extract_docstrings("", "python"), "")

# ─── clean_for_embed integration ─────────────────────────────────────

class TestCleanForEmbedDocstrings(unittest.TestCase):
    def test_docstrings_attached_to_cleaned_record(self):
        raw = {
            "path": "x.py",
            "language": "python",
            "text": '"""why this module exists."""\n\ndef foo(): return 1\n',
            "sha": "abc",
        }
        out = oi.clean_for_embed(raw)
        self.assertIn("docstrings", out)
        self.assertIn("why this module exists.", out["docstrings"])

    def test_no_docstrings_field_for_error_rows(self):
        raw = {"path": "x.py", "language": "python", "error": "read failed"}
        out = oi.clean_for_embed(raw)
        self.assertNotIn("docstrings", out)

    def test_empty_docstrings_for_doc_free_source(self):
        raw = {
            "path": "x.py",
            "language": "python",
            "text": "def foo(): return 1\n",
            "sha": "abc",
        }
        out = oi.clean_for_embed(raw)
        self.assertEqual(out["docstrings"], "")

# ─── chunk_record dual-emission ──────────────────────────────────────

class TestChunkRecordDualEmission(unittest.TestCase):
    def test_emits_code_chunks_with_kind_code(self):
        cleaned = {
            "path": "x.py",
            "language": "python",
            "sha": "a",
            "cleaned": "def foo():\n    return 1\n",
            "docstrings": "",
        }
        chunks = oi.chunk_record(cleaned)
        kept = [c for c in chunks if c.get("kept")]
        self.assertTrue(kept)
        self.assertTrue(all(c["kind"] == "code" for c in kept))

    def test_emits_doc_chunks_when_docstrings_present(self):
        cleaned = {
            "path": "x.py",
            "language": "python",
            "sha": "a",
            "cleaned": "def foo():\n    return 1\n",
            "docstrings": "Top-level rationale: this module exists because...",
        }
        chunks = oi.chunk_record(cleaned)
        kept = [c for c in chunks if c.get("kept")]
        code = [c for c in kept if c["kind"] == "code"]
        doc = [c for c in kept if c["kind"] == "doc"]
        self.assertTrue(code, "should still emit code chunks")
        self.assertTrue(doc, "should emit at least one doc chunk")
        self.assertIn("rationale", doc[0]["text"])

    def test_no_doc_chunks_when_docstrings_empty(self):
        cleaned = {
            "path": "x.py",
            "language": "python",
            "sha": "a",
            "cleaned": "def foo():\n    return 1\n",
            "docstrings": "   \n  ",  # whitespace-only
        }
        chunks = oi.chunk_record(cleaned)
        kept = [c for c in chunks if c.get("kept")]
        self.assertTrue(all(c["kind"] == "code" for c in kept))

    def test_chunk_indices_unique_across_code_and_doc(self):
        cleaned = {
            "path": "x.py",
            "language": "python",
            "sha": "a",
            "cleaned": "def foo():\n    return 1\n",
            "docstrings": "doc one. doc two. doc three.",
        }
        chunks = oi.chunk_record(cleaned)
        kept = [c for c in chunks if c.get("kept")]
        indices = [c["chunk_idx"] for c in kept]
        self.assertEqual(len(set(indices)), len(indices),
                         "chunk_idx values must be unique within a file")

# ─── Schema migration ────────────────────────────────────────────────

class TestKindColumnMigration(unittest.TestCase):
    def test_new_db_has_kind_column(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            conn = oi.open_db(tmp, create=True)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("kind", cols)
            # Index is present too — both fresh + migrated dbs get it.
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_chunk_kind'"
            ).fetchone()
            self.assertIsNotNone(idx)
            conn.close()

    def test_migration_adds_kind_to_pre_v132_db(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            db = oi.db_path(tmp)
            db.parent.mkdir(parents=True, exist_ok=True)
            # Build a pre-v1.32 schema by hand (no `kind`).
            conn = sqlite3.connect(str(db))
            conn.execute("""
                CREATE TABLE code_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    chunk_idx INTEGER NOT NULL,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    language TEXT NOT NULL
                )
            """)
            conn.commit()
            # Sanity: kind absent
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertNotIn("kind", cols)
            conn.close()
            # Reopen via the indexer (runs migration)
            conn = oi.open_db(tmp, create=True)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
            self.assertIn("kind", cols)
            conn.close()

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            conn = oi.open_db(tmp, create=True)
            conn.close()
            # Reopen twice — must not error or create duplicate column.
            conn = oi.open_db(tmp, create=True)
            cols = [row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")]
            self.assertEqual(cols.count("kind"), 1)
            conn.close()

if __name__ == "__main__":
    unittest.main()
