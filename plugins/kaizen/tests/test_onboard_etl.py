#!/usr/bin/env python3
"""Tests for the v1.31 two-fold ETL pipeline in onboard_index.py.

Two SQLite-resident layers — no JSONL in the hot path:

    iter_source_files()
        ↓
    read_raw_file()                  ← lossless capture; errors as rows
        ↓
    do_dump()                        ← INSERT OR REPLACE into code_files_raw
        ↓
    do_filter() (clean + chunk + embed)
        ↓
    code_files + code_chunks (existing chunked search tables)

The `code_files_raw` table is the source of truth for "what we saw on
disk." Re-running do_filter alone (e.g. after a new comment-strip rule
lands) does NOT re-read the filesystem — it re-reads the raw table.
Errors surface as rows (`error IS NOT NULL`) instead of being
collapsed into a counter.

Run:
    python3 -m unittest tests.test_onboard_etl -v
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import onboard_index as oi  # noqa: E402


def _fake_vec(seed: int = 1) -> bytes:
    return struct.pack("384f", *([seed / 100.0] * 384))


class TestReadRawFile(unittest.TestCase):
    """Stage 1 — lossless capture. Always returns a row; error captured in-row."""

    def test_returns_row_with_text_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "main.py"
            p.write_text("def f():\n    return 1\n")
            rec = oi.read_raw_file(p, root)
            self.assertIsNone(rec.get("error"))
            self.assertEqual(rec["path"], "main.py")
            self.assertEqual(rec["language"], "python")
            self.assertEqual(rec["text"], "def f():\n    return 1\n")
            self.assertEqual(rec["bytes"], len(rec["text"].encode()))
            self.assertTrue(rec["sha"])

    def test_captures_unicode_decode_error_as_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "binary.py"
            p.write_bytes(b"\xff\xfe\x00\x00not utf8\xff")
            rec = oi.read_raw_file(p, root)
            self.assertEqual(rec["path"], "binary.py")
            self.assertIn("error", rec)
            self.assertIn("decode", rec["error"].lower())
            self.assertNotIn("text", rec)

    def test_captures_oserror_as_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "missing.py"
            rec = oi.read_raw_file(p, root)
            self.assertEqual(rec["path"], "missing.py")
            self.assertIn("error", rec)


class TestCleanForEmbed(unittest.TestCase):
    """Stage 2a — comment-strip + whitespace-normalize a raw record."""

    def test_strips_comments_and_normalizes(self) -> None:
        raw = {
            "path": "main.py",
            "language": "python",
            "text": "# header comment\ndef f():\n    return 1\n",
            "sha": "abc",
            "bytes": 0,
        }
        out = oi.clean_for_embed(raw)
        self.assertNotIn("header comment", out["cleaned"])
        self.assertIn("def f", out["cleaned"])
        self.assertTrue(out["snippet"])
        self.assertEqual(out["sha"], "abc")

    def test_passes_through_error_rows(self) -> None:
        raw = {"path": "binary.py", "error": "decode failed"}
        out = oi.clean_for_embed(raw)
        self.assertEqual(out["error"], "decode failed")
        self.assertNotIn("cleaned", out)


class TestChunkRecord(unittest.TestCase):
    """Stage 2b — split cleaned record into per-chunk records."""

    def test_returns_kept_chunks_for_non_empty(self) -> None:
        rec = {
            "path": "main.py",
            "language": "python",
            "sha": "abc",
            "cleaned": "def f():\n    return 1\n" * 30,  # enough for >=1 chunk
        }
        chunks = oi.chunk_record(rec)
        self.assertTrue(chunks)
        for c in chunks:
            self.assertTrue(c["kept"])
            self.assertEqual(c["path"], "main.py")
            self.assertEqual(c["sha"], "abc")
            self.assertEqual(c["language"], "python")
            self.assertIn("text", c)
            self.assertIn("chunk_idx", c)

    def test_emits_dropped_row_for_empty_after_clean(self) -> None:
        rec = {
            "path": "blank.py",
            "language": "python",
            "sha": "def",
            "cleaned": "",  # nothing to chunk
        }
        chunks = oi.chunk_record(rec)
        self.assertEqual(len(chunks), 1)
        self.assertFalse(chunks[0]["kept"])
        self.assertIn("kept_reason", chunks[0])

    def test_passes_through_error_rows(self) -> None:
        rec = {"path": "binary.py", "error": "decode failed"}
        chunks = oi.chunk_record(rec)
        self.assertEqual(len(chunks), 1)
        self.assertFalse(chunks[0]["kept"])
        self.assertEqual(chunks[0]["error"], "decode failed")


class TestCodeFilesRawSchema(unittest.TestCase):
    """`code_files_raw` is the lossless capture table — must be created by
    open_db so do_dump can write into it on a fresh db."""

    def test_open_db_creates_code_files_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = oi.open_db(root, create=True)
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("code_files_raw", tables)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(code_files_raw)")}
            for required in ("path", "sha", "language", "bytes", "sloc_raw",
                             "mtime", "text", "error", "captured_at"):
                self.assertIn(required, cols, f"code_files_raw missing column: {required}")
            conn.close()


class TestDoDump(unittest.TestCase):
    """do_dump walks the source tree and INSERT OR REPLACEs into code_files_raw.
    One row per file. Error rows preserved with text=NULL, error=<reason>."""

    def _build_project(self, tmpdir: Path) -> Path:
        root = tmpdir / "proj"
        root.mkdir()
        (root / "main.py").write_text("def f():\n    return 1\n")
        (root / "other.py").write_text("x = 2\n")
        (root / "binary.py").write_bytes(b"\xff\xfenot utf8\xff")
        return root

    def test_writes_one_row_per_file_including_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._build_project(Path(tmp))
            result = oi.do_dump(root, use_git=False)
            self.assertEqual(result["total"], 3)
            self.assertEqual(result["errors"], 1)
            conn = oi.open_db(root, create=False)
            rows = conn.execute(
                "SELECT path, text, error FROM code_files_raw ORDER BY path"
            ).fetchall()
            paths = [r["path"] for r in rows]
            self.assertEqual(paths, ["binary.py", "main.py", "other.py"])
            by_path = {r["path"]: r for r in rows}
            self.assertEqual(by_path["binary.py"]["text"], None)
            self.assertIn("decode", by_path["binary.py"]["error"].lower())
            self.assertEqual(by_path["main.py"]["error"], None)
            self.assertIn("def f", by_path["main.py"]["text"])
            conn.close()


class TestDoFilter(unittest.TestCase):
    """do_filter reads from code_files_raw, populates code_files + code_chunks.
    Skips error rows. Embedding is mocked."""

    def test_populates_chunks_from_raw_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "main.py").write_text("def f():\n    return 1\n" * 30)
            (root / "binary.py").write_bytes(b"\xff\xfenot utf8\xff")
            # Stage 1: lossless dump.
            oi.do_dump(root, use_git=False)
            # Stage 2: filter + embed (mocked).
            fake_batch = lambda texts: ([_fake_vec(i + 1) for i in range(len(texts))], 384)
            with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
                result = oi.do_filter(root)
            self.assertEqual(result["files_indexed"], 1)
            self.assertGreaterEqual(result["chunks"], 1)
            self.assertEqual(result["errors_skipped"], 1)
            conn = oi.open_db(root, create=False)
            n_files = conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
            n_chunks = conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
            self.assertEqual(n_files, 1)
            self.assertGreaterEqual(n_chunks, 1)
            conn.close()


class TestDiagnosticHelpers(unittest.TestCase):
    """do_raw_errors + do_dropped surface stage-1 and stage-2 failures."""

    def test_raw_errors_lists_decode_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "ok.py").write_text("x = 1\n")
            (root / "binary.py").write_bytes(b"\xff\xfe\x00\x00\xff")
            oi.do_dump(root, use_git=False)
            errs = oi.do_raw_errors(root)
            self.assertEqual(len(errs), 1)
            self.assertEqual(errs[0]["path"], "binary.py")
            self.assertIn("decode", errs[0]["error"].lower())

    def test_dropped_lists_files_with_no_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "real.py").write_text("def f():\n    return 1\n" * 30)
            (root / "comments.py").write_text("# just a comment\n# another\n# third\n")
            oi.do_dump(root, use_git=False)
            fake_batch = lambda texts: ([_fake_vec(i + 1) for i in range(len(texts))], 384)
            with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
                oi.do_filter(root)
            dropped = oi.do_dropped(root)
            paths = [d["path"] for d in dropped]
            self.assertIn("comments.py", paths)
            self.assertNotIn("real.py", paths)
            for d in dropped:
                self.assertEqual(d["reason"], "empty_after_clean_or_no_chunks")


class TestStagesAreIndependent(unittest.TestCase):
    """Re-running do_filter without touching the filesystem must work as long
    as code_files_raw is populated. This is the reproducibility guarantee."""

    def test_filter_alone_reads_only_from_raw_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "main.py").write_text("def f():\n    return 1\n" * 30)
            oi.do_dump(root, use_git=False)
            # Delete the source file — do_filter must still succeed
            # because it reads from code_files_raw, not the filesystem.
            (root / "main.py").unlink()
            fake_batch = lambda texts: ([_fake_vec(i + 1) for i in range(len(texts))], 384)
            with patch.object(oi._kz_embed, "embed_batch", side_effect=fake_batch):
                result = oi.do_filter(root)
            self.assertEqual(result["files_indexed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
