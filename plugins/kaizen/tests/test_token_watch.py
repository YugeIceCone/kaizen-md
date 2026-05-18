"""TDD: watcher event → token-map DB update.

Two-tier test pattern (same as test_token_extractor.py / test_token_db.py):

  * Delete-path test runs in-process — `process_file_event(event="deleted")`
    never touches tree-sitter, so system python can drive it directly via
    the in-process `_token_watch` import.
  * Modified-path tests invoke the script's `__main__ --test` mode via
    `uv run --script`, which loads the PEP-723 tree-sitter deps and runs
    `process_file_event` inside that uv venv. Each invocation takes a
    JSON payload (db_path, root, rel_path, event) on stdin.

This mirrors the production wire-up: the kaizen-watch daemon will call
`process_file_event` from a long-lived process that already has the uv
venv resolved (T7 wires it up).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills" / "workflow" / "scripts" / "_token_watch.py"
)

# In-process import of TokenDB + the watcher entry point. The watcher
# module itself is stdlib-only at import time — tree-sitter only loads
# lazily inside `_token_extractor._get_parser` when a modified-event
# actually parses a real source file.
sys.path.insert(0, str(SCRIPT.parent))
from _token_db import TokenDB  # noqa: E402
from _token_watch import process_file_event  # noqa: E402


def _watch_via_uv(db_path: Path, root: Path, rel_path: str, event: str) -> None:
    """Invoke `_token_watch.py --test` inside the uv venv (tree-sitter loaded).

    Used for modified events on real source files (where extract_slots needs
    the grammar). The script writes directly to `db_path`; caller re-opens
    the DB to inspect post-state.
    """
    payload = json.dumps({
        "db_path": str(db_path),
        "root": str(root),
        "rel_path": rel_path,
        "event": event,
    })
    r = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "--test"],
        input=payload, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise AssertionError(f"watcher failed: {r.stderr}")


class TestDeleteMarksPathGone(unittest.TestCase):
    """Delete-event path needs no tree-sitter; runs purely in-process."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        (self.root / "x.rs").write_bytes(b"fn alpha() {}\n")
        self.db = TokenDB(self.root / ".kaizen" / "token-map.db")
        self.db.init_schema()
        # Seed a row so mark_path_gone has something to flip.
        self.db.upsert_file(
            path="x.rs", blake3="seed", language="rust",
            grammar_version="0.23.0", mtime=1,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_marks_path_gone(self):
        process_file_event(self.db, self.root, Path("x.rs"), event="deleted")
        row = self.db.conn.execute(
            "SELECT path_gone FROM files WHERE path=?", ("x.rs",),
        ).fetchone()
        self.assertEqual(row["path_gone"], 1)

    def test_missing_on_disk_treated_as_delete(self):
        # File doesn't exist → even a "modified" event should mark_path_gone.
        process_file_event(self.db, self.root, Path("ghost.rs"), event="modified")
        # ghost.rs was never inserted; mark_path_gone is a no-op UPDATE.
        # Just verify no exception + no orphan row created.
        row = self.db.conn.execute(
            "SELECT * FROM files WHERE path=?", ("ghost.rs",),
        ).fetchone()
        self.assertIsNone(row)

    def test_excluded_path_is_no_op(self):
        # V21/V22: target/ is excluded; event must be silently dropped.
        (self.root / "target").mkdir()
        (self.root / "target" / "build.rs").write_bytes(b"fn x() {}\n")
        process_file_event(
            self.db, self.root, Path("target/build.rs"), event="modified",
        )
        row = self.db.conn.execute(
            "SELECT * FROM files WHERE path=?", ("target/build.rs",),
        ).fetchone()
        self.assertIsNone(row)


class TestModifiedEventViaUvVenv(unittest.TestCase):
    """Modified-event path requires tree-sitter → driven via uv subprocess."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()
        self.db_path = self.root / ".kaizen" / "token-map.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _open_db(self) -> TokenDB:
        db = TokenDB(self.db_path)
        db.init_schema()
        return db

    def test_new_file_event_indexes_it(self):
        (self.root / "x.rs").write_bytes(b"fn alpha() {}\n")
        # Pre-init the schema so the watcher subprocess can open the DB.
        self._open_db().conn.close()

        _watch_via_uv(self.db_path, self.root, "x.rs", "modified")

        db = self._open_db()
        row = db.conn.execute(
            "SELECT * FROM files WHERE path=?", ("x.rs",),
        ).fetchone()
        self.assertIsNotNone(row)
        # Slot 2 should be the `alpha` fn (slot 0 = body, slot 1 = path).
        slot_row = db.conn.execute(
            "SELECT name FROM slots WHERE file_id=? AND kind='fn'",
            (row["file_id"],),
        ).fetchone()
        self.assertIsNotNone(slot_row)
        self.assertEqual(slot_row["name"], "alpha")

    def test_modified_file_diffs_slots_and_tombstones_removed(self):
        # Initial state: two fns.
        f = self.root / "x.rs"
        f.write_bytes(b"fn alpha() {}\nfn beta() {}\n")
        self._open_db().conn.close()

        _watch_via_uv(self.db_path, self.root, "x.rs", "modified")

        db = self._open_db()
        fid = db.conn.execute(
            "SELECT file_id FROM files WHERE path=?", ("x.rs",),
        ).fetchone()["file_id"]
        live_before = db.conn.execute(
            "SELECT name FROM slots WHERE file_id=? AND kind='fn' "
            "AND tombstoned=0 ORDER BY name", (fid,),
        ).fetchall()
        self.assertEqual([r["name"] for r in live_before], ["alpha", "beta"])
        db.conn.close()

        # Edit: drop beta(); only alpha remains.
        f.write_bytes(b"fn alpha() {}\n")
        _watch_via_uv(self.db_path, self.root, "x.rs", "modified")

        db = self._open_db()
        live_after = db.conn.execute(
            "SELECT name FROM slots WHERE file_id=? AND kind='fn' "
            "AND tombstoned=0 ORDER BY name", (fid,),
        ).fetchall()
        self.assertEqual([r["name"] for r in live_after], ["alpha"])
        # The dropped fn's slot row must still exist, just tombstoned.
        tomb = db.conn.execute(
            "SELECT COUNT(*) AS n FROM slots WHERE file_id=? AND kind='fn' "
            "AND tombstoned=1", (fid,),
        ).fetchone()
        self.assertEqual(tomb["n"], 1)


if __name__ == "__main__":
    unittest.main()
