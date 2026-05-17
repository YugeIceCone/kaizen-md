"""Tests for _atomic.py — shared atomic-write helper.

Single source for the tempfile+rename pattern used across handoff
auto-finalize / create, dxm session links, and future writers. Hides
the cross-platform subtleties (os.replace is atomic on POSIX + Win;
tempfile in same dir is required for atomicity).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "skills/workflow/scripts"
sys.path.insert(0, str(_SCRIPTS))


class AtomicBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ─── atomic_write (string content) ───────────────────────────────────


class TestAtomicWriteString(AtomicBase):
    def test_writes_content_to_path(self):
        import _atomic
        target = self.tmp / "out.txt"
        _atomic.atomic_write(target, "hello world\n")
        self.assertEqual(target.read_text(), "hello world\n")

    def test_overwrites_existing(self):
        import _atomic
        target = self.tmp / "exists.txt"
        target.write_text("OLD\n")
        _atomic.atomic_write(target, "NEW\n")
        self.assertEqual(target.read_text(), "NEW\n")

    def test_creates_parent_dirs(self):
        import _atomic
        target = self.tmp / "nested" / "deep" / "file.txt"
        _atomic.atomic_write(target, "x")
        self.assertTrue(target.is_file())

    def test_tempfile_cleaned_up_on_success(self):
        import _atomic
        target = self.tmp / "out.txt"
        _atomic.atomic_write(target, "x")
        # No stray .tmp / .part files left in tmp dir
        leftover = [p for p in self.tmp.iterdir()
                     if p.name.startswith(".") or
                     ".tmp" in p.name or ".part" in p.name]
        self.assertEqual(leftover, [],
                          f"stray tempfiles: {leftover}")

    def test_default_encoding_is_utf8(self):
        import _atomic
        target = self.tmp / "unicode.txt"
        _atomic.atomic_write(target, "ñ → ö ✓")
        self.assertEqual(target.read_text(encoding="utf-8"), "ñ → ö ✓")


# ─── atomic_write_json ───────────────────────────────────────────────


class TestAtomicWriteJson(AtomicBase):
    def test_writes_json_with_default_indent(self):
        import _atomic
        target = self.tmp / "out.json"
        _atomic.atomic_write_json(target, {"a": 1, "b": [2, 3]})
        loaded = json.loads(target.read_text())
        self.assertEqual(loaded, {"a": 1, "b": [2, 3]})

    def test_sort_keys_for_determinism(self):
        import _atomic
        target = self.tmp / "sorted.json"
        _atomic.atomic_write_json(target, {"z": 1, "a": 2})
        body = target.read_text()
        # Sorted keys: "a" appears before "z"
        self.assertLess(body.index('"a"'), body.index('"z"'))


# ─── atomic_append (separate primitive for JSONL appends) ───────────


class TestAtomicAppend(AtomicBase):
    def test_appends_line_to_file(self):
        import _atomic
        target = self.tmp / "log.jsonl"
        _atomic.atomic_append_line(target, '{"a":1}')
        _atomic.atomic_append_line(target, '{"b":2}')
        lines = target.read_text().strip().splitlines()
        self.assertEqual(lines, ['{"a":1}', '{"b":2}'])

    def test_creates_parent_dirs_for_append(self):
        import _atomic
        target = self.tmp / "nested" / "log.jsonl"
        _atomic.atomic_append_line(target, "x")
        self.assertTrue(target.is_file())


# ─── error paths ─────────────────────────────────────────────────────


class TestAtomicErrors(AtomicBase):
    def test_write_to_unwritable_dir_raises(self):
        import _atomic
        # Use a non-existent device path (Linux) that can't be created
        target = Path("/proc/should-not-write/file.txt")
        with self.assertRaises(OSError):
            _atomic.atomic_write(target, "x")


if __name__ == "__main__":
    unittest.main()
