"""Tests for kaizen-io — single + batch atomic read/write."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_SCRIPT = _KZ_DIR / "scripts/io/io.py"


def _run(*args, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        input=stdin, capture_output=True, text=True, timeout=10,
        env=os.environ.copy(),
    )


class TestScriptHealth(unittest.TestCase):
    def test_script_parses(self):
        with open(_SCRIPT) as f:
            compile(f.read(), str(_SCRIPT), "exec")


class TestSingle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_then_read(self):
        target = self.tmp / "out.txt"
        r1 = _run("write", str(target), "--content", "alpha")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = _run("read", str(target))
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r2.stdout, "alpha")

    def test_write_stdin(self):
        target = self.tmp / "out.txt"
        r = _run("write", str(target), "--stdin", stdin="from stdin")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(target.read_text(), "from stdin")

    def test_write_json_emits_metadata(self):
        target = self.tmp / "out.txt"
        r = _run("write", str(target), "--content", "x", "--json")
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["bytes"], 1)

    def test_read_missing_exits_1(self):
        r = _run("read", str(self.tmp / "vanished.txt"))
        self.assertEqual(r.returncode, 1)


class TestBatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_5_writes_in_one_call(self):
        ops = [
            {"op": "write", "file_path": str(self.tmp / f"f{i}.txt"),
             "content": f"content-{i}"}
            for i in range(5)
        ]
        r = _run("batch", stdin=json.dumps(ops))
        self.assertEqual(r.returncode, 0, r.stderr)
        results = json.loads(r.stdout)
        self.assertEqual(len(results), 5)
        for i, res in enumerate(results):
            self.assertTrue(res["ok"])
            self.assertEqual((self.tmp / f"f{i}.txt").read_text(),
                              f"content-{i}")

    def test_mixed_write_then_read_two_phase(self):
        """The two-phase fix: writes complete before reads start. A
        batch like [write a, read a] must return read=ok (the read
        sees the write from phase 1)."""
        target = self.tmp / "x.txt"
        ops = [
            {"op": "write", "file_path": str(target), "content": "X"},
            {"op": "read",  "file_path": str(target)},
        ]
        r = _run("batch", stdin=json.dumps(ops))
        self.assertEqual(r.returncode, 0)
        results = json.loads(r.stdout)
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[1]["ok"])
        self.assertEqual(results[1]["content"], "X")

    def test_result_preserves_input_order(self):
        """Even with phase reordering internally, result order = input order."""
        ops = [
            {"op": "read",  "file_path": str(self.tmp / "noexist.txt")},
            {"op": "write", "file_path": str(self.tmp / "y.txt"), "content": "Y"},
            {"op": "read",  "file_path": str(self.tmp / "y.txt")},
        ]
        r = _run("batch", stdin=json.dumps(ops))
        results = json.loads(r.stdout)
        self.assertEqual(results[0]["op"], "read")
        self.assertEqual(results[1]["op"], "write")
        self.assertEqual(results[2]["op"], "read")
        self.assertFalse(results[0]["ok"])  # first read of nonexistent
        self.assertTrue(results[1]["ok"])
        self.assertTrue(results[2]["ok"])
        self.assertEqual(results[2]["content"], "Y")

    def test_write_bytes_base64(self):
        import base64
        target = self.tmp / "blob.bin"
        ops = [
            {"op": "write_bytes", "file_path": str(target),
             "bytes_base64": base64.b64encode(b"\x00\x01\x02").decode()},
        ]
        r = _run("batch", stdin=json.dumps(ops))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(target.read_bytes(), b"\x00\x01\x02")

    def test_missing_file_path_returns_error(self):
        ops = [{"op": "write", "content": "x"}]  # missing file_path
        r = _run("batch", stdin=json.dumps(ops))
        results = json.loads(r.stdout)
        self.assertFalse(results[0]["ok"])
        self.assertIn("file_path", results[0]["error"])

    def test_unknown_op_returns_error(self):
        ops = [{"op": "frobnicate", "file_path": str(self.tmp / "x.txt")}]
        r = _run("batch", stdin=json.dumps(ops))
        results = json.loads(r.stdout)
        self.assertFalse(results[0]["ok"])
        self.assertIn("unknown op", results[0]["error"])

    def test_invalid_json_stdin_exits_2(self):
        r = _run("batch", stdin="not-json")
        self.assertEqual(r.returncode, 2)

    def test_non_array_stdin_exits_2(self):
        r = _run("batch", stdin='{"not": "an array"}')
        self.assertEqual(r.returncode, 2)

    def test_batch_exit_1_when_any_failed(self):
        ops = [
            {"op": "write", "file_path": str(self.tmp / "ok.txt"), "content": "x"},
            {"op": "read",  "file_path": str(self.tmp / "missing.txt")},
        ]
        r = _run("batch", stdin=json.dumps(ops))
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
