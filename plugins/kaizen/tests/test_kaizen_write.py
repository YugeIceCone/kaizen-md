"""Tests for kaizen-write — CLI exposing _atomic.atomic_write to shell consumers.

A tool wrapper around the atomic-write util — agents that want to
atomically write a file from shell can call kaizen-write without
needing to use Python directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS = _KZ_DIR / "scripts/io"
_WRITE_PY = _SCRIPTS / "kaizen_write.py"


class WriteBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_WRITE_PY), *args],
            input=stdin, capture_output=True, text=True, timeout=15,
        )


class TestKaizenWrite(WriteBase):
    def test_writes_content_from_stdin(self):
        target = self.tmp / "out.txt"
        r = self._run("--path", str(target), "--stdin", stdin="hello world\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(target.read_text(), "hello world\n")

    def test_writes_content_from_flag(self):
        target = self.tmp / "out2.txt"
        r = self._run("--path", str(target), "--content", "inline")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(target.read_text(), "inline")

    def test_creates_parent_dirs(self):
        target = self.tmp / "deep" / "nest" / "f.txt"
        r = self._run("--path", str(target), "--content", "x")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(target.is_file())

    def test_json_mode_validates_and_writes(self):
        target = self.tmp / "out.json"
        payload = '{"a": 1, "b": 2}'
        r = self._run("--path", str(target), "--json-from-stdin",
                       stdin=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        loaded = json.loads(target.read_text())
        self.assertEqual(loaded, {"a": 1, "b": 2})

    def test_json_mode_rejects_invalid(self):
        target = self.tmp / "out.json"
        r = self._run("--path", str(target), "--json-from-stdin",
                       stdin="not-json")
        self.assertNotEqual(r.returncode, 0)
        # Target NOT touched
        self.assertFalse(target.exists())

    def test_bytes_mode_decodes_base64(self):
        import base64
        target = self.tmp / "blob.bin"
        payload = bytes(range(64))
        b64 = base64.b64encode(payload).decode("ascii")
        r = self._run("--path", str(target), "--bytes-base64", b64)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(target.read_bytes(), payload)

    def test_append_mode_appends_line(self):
        target = self.tmp / "log.jsonl"
        target.write_text('{"a":1}\n')
        r = self._run("--path", str(target), "--append-line", "--content", '{"b":2}')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(target.read_text(),
                          '{"a":1}\n{"b":2}\n')

    def test_help_works(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("kaizen-write", r.stdout)

    def test_missing_path_arg_errors(self):
        r = self._run("--content", "x")
        self.assertNotEqual(r.returncode, 0)

    def test_no_content_source_errors(self):
        r = self._run("--path", str(self.tmp / "x"))
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
