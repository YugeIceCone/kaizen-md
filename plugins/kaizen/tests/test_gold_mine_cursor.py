"""Phase 1 — tests for gold_mine cursor + mtime short-circuit + tail-diff.

Pure stdlib; sandboxes via KAIZEN_DIR. Validates the 3-level short-circuit:
    (1) mtime unchanged → exit (no read)
    (2) inode changed → re-scan from byte 0 (rotation)
    (3) tail-hash same → exit
    else → read from byte_offset, return only new lines.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "skills" / "workflow" / "scripts"))

import gold_mine  # noqa: E402


class CursorBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.kaizen_dir = self.tmp / "kz"
        self.kaizen_dir.mkdir()
        self._orig = os.environ.get("KAIZEN_DIR")
        os.environ["KAIZEN_DIR"] = str(self.kaizen_dir)
        self.target = self.tmp / "events.jsonl"

    def tearDown(self):
        self._tmp.cleanup()
        if self._orig is None:
            os.environ.pop("KAIZEN_DIR", None)
        else:
            os.environ["KAIZEN_DIR"] = self._orig

    def _write_lines(self, *lines: str) -> None:
        with self.target.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")


class TestCursorPath(CursorBase):
    def test_cursor_path_inside_project_slug(self):
        p = gold_mine.cursor_path()
        self.assertTrue(str(p).startswith(str(self.kaizen_dir / "gold")))
        self.assertTrue(str(p).endswith("mine-cursor.json"))

    def test_load_cursor_missing_returns_empty_dict(self):
        self.assertEqual(gold_mine.load_cursor(), {})

    def test_save_cursor_round_trips(self):
        gold_mine.save_cursor({"dxm": {"inode": 7, "byte_offset": 100,
                                         "sha256_tail_4kb": "abc",
                                         "line_count": 5, "mtime": 1.0}})
        loaded = gold_mine.load_cursor()
        self.assertEqual(loaded["dxm"]["inode"], 7)
        self.assertEqual(loaded["dxm"]["byte_offset"], 100)


class TestTailDiff(CursorBase):
    def test_first_read_returns_all_lines(self):
        self._write_lines("a", "b", "c")
        lines, new_cursor = gold_mine.read_new_lines(self.target, prior=None)
        self.assertEqual([l.rstrip("\n") for l in lines], ["a", "b", "c"])
        self.assertEqual(new_cursor["line_count"], 3)
        self.assertGreater(new_cursor["byte_offset"], 0)

    def test_mtime_same_short_circuits(self):
        self._write_lines("a", "b")
        _, c1 = gold_mine.read_new_lines(self.target, prior=None)
        # Same prior; mtime unchanged → empty list + same cursor returned.
        lines, c2 = gold_mine.read_new_lines(self.target, prior=c1)
        self.assertEqual(lines, [])
        self.assertEqual(c1["mtime"], c2["mtime"])

    def test_append_returns_only_new_lines(self):
        self._write_lines("a", "b")
        _, c1 = gold_mine.read_new_lines(self.target, prior=None)
        # Force mtime change.
        time.sleep(0.02)
        self._write_lines("c", "d")
        lines, c2 = gold_mine.read_new_lines(self.target, prior=c1)
        self.assertEqual([l.rstrip("\n") for l in lines], ["c", "d"])
        self.assertEqual(c2["line_count"], 4)

    def test_inode_change_rescans_from_zero(self):
        self._write_lines("a", "b")
        _, c1 = gold_mine.read_new_lines(self.target, prior=None)
        # Rotate: delete + recreate (new inode).
        self.target.unlink()
        time.sleep(0.02)
        self._write_lines("X", "Y", "Z")
        lines, c2 = gold_mine.read_new_lines(self.target, prior=c1)
        self.assertEqual([l.rstrip("\n") for l in lines], ["X", "Y", "Z"])
        self.assertNotEqual(c1["inode"], c2["inode"])

    def test_tail_hash_short_circuit_when_mtime_changed_but_content_same(self):
        # Some filesystems update mtime without content change (e.g. touch).
        self._write_lines("a", "b", "c")
        _, c1 = gold_mine.read_new_lines(self.target, prior=None)
        # Bump mtime without changing content.
        now = time.time() + 1
        os.utime(self.target, (now, now))
        lines, c2 = gold_mine.read_new_lines(self.target, prior=c1)
        self.assertEqual(lines, [])  # tail hash matches → short-circuit
        self.assertEqual(c2["sha256_tail_4kb"], c1["sha256_tail_4kb"])

    def test_missing_file_returns_empty(self):
        lines, cur = gold_mine.read_new_lines(self.tmp / "missing.jsonl",
                                                prior=None)
        self.assertEqual(lines, [])
        self.assertEqual(cur, {})


if __name__ == "__main__":
    unittest.main()
