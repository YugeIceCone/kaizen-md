"""TDD: verify tree-sitter deps reachable via the PEP-723 uv-script
invocation path that _token_db.py uses in production.

Phase 1 (T1) — confirms the `#!/usr/bin/env -S uv run --script` shebang
+ inline dep manifest in `_token_db.py` resolves all 3 grammars when
the script is actually invoked. (System Python doesn't see uv-managed
deps; that's by design — uv keeps per-script venvs isolated.)

T2 — adds 12 schema/CRUD/rename/tombstone/version-bump tests that
exercise the in-process `TokenDB` API (stdlib sqlite3 only, no tree-
sitter needed for these tests).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "workflow" / "scripts" / "_token_db.py"
)

# T2: in-process import of the TokenDB module (stdlib-only path —
# sqlite3 lives in CPython, so no uv-script invocation needed for these
# tests). The script's PEP-723 deps are only required when tree-sitter
# extraction runs (T3+).
sys.path.insert(0, str(SCRIPT.parent))
from _token_db import TokenDB, Slot  # noqa: E402


def _uv_import_check(modname: str) -> subprocess.CompletedProcess:
    """Run the script via uv (which loads its PEP-723 deps) and probe an import."""
    return subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "-c",
         f"import {modname}; print('ok')"],
        capture_output=True, text=True, timeout=30,
    )


class TestTreesitterDepAvailable(unittest.TestCase):
    def test_script_file_exists(self):
        self.assertTrue(SCRIPT.exists(), f"missing: {SCRIPT}")

    def test_tree_sitter_importable_via_uv_script(self):
        r = _uv_import_check("tree_sitter")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_tree_sitter_rust_importable_via_uv_script(self):
        r = _uv_import_check("tree_sitter_rust")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_tree_sitter_python_importable_via_uv_script(self):
        r = _uv_import_check("tree_sitter_python")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("ok", r.stdout)


# ─── T2: Schema init ─────────────────────────────────────────────────


class TestSchemaInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TokenDB(Path(self.tmp.name) / "tokens.db")
        self.db.init_schema()

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_files_table_exists(self):
        rows = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_slots_table_exists(self):
        rows = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='slots'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_slots_by_name_table_exists(self):
        rows = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='slots_by_name'"
        ).fetchall()
        self.assertEqual(len(rows), 1)


# ─── T2: File upsert + V1 rename detection ───────────────────────────


class TestUpsertFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TokenDB(Path(self.tmp.name) / "tokens.db")
        self.db.init_schema()

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_first_upsert_allocates_file_id(self):
        fid = self.db.upsert_file(
            path="src/foo.rs", blake3="abc", language="rust",
            grammar_version="0.23.0", mtime=100,
        )
        self.assertEqual(fid, 1)

    def test_second_upsert_same_path_keeps_id(self):
        fid1 = self.db.upsert_file(
            path="src/foo.rs", blake3="abc", language="rust",
            grammar_version="0.23.0", mtime=100,
        )
        fid2 = self.db.upsert_file(
            path="src/foo.rs", blake3="abc2", language="rust",
            grammar_version="0.23.0", mtime=200,
        )
        self.assertEqual(fid1, fid2)

    def test_rename_detected_by_blake3_match(self):
        # V1: file with same blake3 appearing at new path → reuse file_id
        fid1 = self.db.upsert_file(
            path="src/foo.rs", blake3="abc", language="rust",
            grammar_version="0.23.0", mtime=100,
        )
        self.db.mark_path_gone("src/foo.rs")
        fid2 = self.db.upsert_file(
            path="src/bar.rs", blake3="abc", language="rust",
            grammar_version="0.23.0", mtime=200,
        )
        self.assertEqual(fid1, fid2)


# ─── T2: Slot upsert + V7/V32 name table + tombstone ─────────────────


class TestSlotUpsert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TokenDB(Path(self.tmp.name) / "tokens.db")
        self.db.init_schema()
        self.fid = self.db.upsert_file(
            path="src/foo.rs", blake3="abc", language="rust",
            grammar_version="0.23.0", mtime=100,
        )

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_first_slot_added(self):
        self.db.upsert_slots(self.fid, [
            Slot(slot=0, kind="body", name=None, parent="",
                 byte_start=0, byte_end=100, body=b"...", content_hash="h0"),
        ])
        row = self.db.get_slot(self.fid, 0)
        self.assertEqual(row["kind"], "body")

    def test_name_table_populated_for_named_slots(self):
        self.db.upsert_slots(self.fid, [
            Slot(slot=2, kind="fn", name="bar", parent="",
                 byte_start=10, byte_end=50, body=b"fn bar() {}", content_hash="h1"),
        ])
        slot = self.db.lookup_by_name(self.fid, kind="fn", name="bar", parent="")
        self.assertEqual(slot, 2)

    def test_tombstone_removed_slot(self):
        self.db.upsert_slots(self.fid, [
            Slot(slot=2, kind="fn", name="bar", parent="",
                 byte_start=10, byte_end=50, body=b"fn bar() {}", content_hash="h1"),
        ])
        # New parse, slot 2 missing → tombstone
        self.db.tombstone_slot(self.fid, 2)
        row = self.db.get_slot(self.fid, 2)
        self.assertEqual(row["tombstoned"], 1)


# ─── T2: V25 IMMEDIATE-tx atomic version bump ────────────────────────


class TestVersionBumpAtomic(unittest.TestCase):
    """V25 — IMMEDIATE-tx wrapping; readers see fully old or fully new."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TokenDB(Path(self.tmp.name) / "tokens.db")
        self.db.init_schema()
        self.fid = self.db.upsert_file(
            path="x.rs", blake3="a", language="rust",
            grammar_version="0.23.0", mtime=1,
        )

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_bump_increments_version(self):
        v0 = self.db.get_file_version(self.fid)
        self.db.bump_file_version(self.fid)
        v1 = self.db.get_file_version(self.fid)
        self.assertEqual(v1, v0 + 1)


# ─── T2: lookup_by_name helper coverage ──────────────────────────────


class TestLookupByName(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = TokenDB(Path(self.tmp.name) / "tokens.db")
        self.db.init_schema()
        self.fid = self.db.upsert_file(
            path="src/foo.py", blake3="abc", language="python",
            grammar_version="0.23.0", mtime=100,
        )

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_lookup_by_name_happy_path(self):
        self.db.upsert_slots(self.fid, [
            Slot(slot=3, kind="fn", name="m", parent="C",
                 byte_start=0, byte_end=10, body=b"def m(self):",
                 content_hash="h2"),
        ])
        slot = self.db.lookup_by_name(self.fid, kind="fn", name="m", parent="C")
        self.assertEqual(slot, 3)

    def test_lookup_by_name_miss_returns_none(self):
        slot = self.db.lookup_by_name(
            self.fid, kind="fn", name="does_not_exist", parent="",
        )
        self.assertIsNone(slot)


if __name__ == "__main__":
    unittest.main()
