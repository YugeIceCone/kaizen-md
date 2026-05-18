"""Tests for kaizen-io `read` extended to multi-arg.

Today: `kaizen-io read PATH` reads ONE file. For N files, callers must
build a JSON array + pipe through `kaizen-io batch` — ceremony.

After: `kaizen-io read PATH1 PATH2 PATH3 [--json]` reads N files in
parallel (same _run_batch primitive `batch` already uses), returns:
  - default: concatenation with `\\n=== <path> ===\\n` separators
  - --json:  array of {file_path, ok, content?, error?} envelopes

Back-compat: `kaizen-io read PATH` (single arg) keeps its current
behavior exactly — raw content to stdout (no separator).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_KZ_DIR = Path(__file__).resolve().parent.parent
_IO_PY = _KZ_DIR / "skills/workflow/scripts/io.py"


class _ReadBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_IO_PY), "read", *args],
            capture_output=True, text=True, timeout=15,
        )


class TestSingleFileBackCompat(_ReadBase):
    def test_single_arg_returns_raw_content(self):
        p = self._write("a.txt", "hello\n")
        r = self._run(str(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "hello\n")

    def test_single_arg_json_returns_envelope(self):
        p = self._write("a.txt", "hello\n")
        r = self._run(str(p), "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        # Single-arg --json keeps single-envelope shape (back-compat)
        self.assertEqual(data["file_path"], str(p))
        self.assertEqual(data["content"], "hello\n")
        self.assertTrue(data["ok"])


class TestMultiFileRead(_ReadBase):
    def test_two_files_default_concat_with_separators(self):
        a = self._write("a.txt", "alpha\n")
        b = self._write("b.txt", "beta\n")
        r = self._run(str(a), str(b))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        # Both files present, in input order, with path separators
        self.assertIn("alpha", out)
        self.assertIn("beta", out)
        self.assertIn(str(a), out)
        self.assertIn(str(b), out)
        self.assertLess(out.index("alpha"), out.index("beta"))

    def test_two_files_json_returns_array(self):
        a = self._write("a.txt", "alpha\n")
        b = self._write("b.txt", "beta\n")
        r = self._run(str(a), str(b), "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["file_path"], str(a))
        self.assertEqual(data[0]["content"], "alpha\n")
        self.assertEqual(data[1]["file_path"], str(b))
        self.assertEqual(data[1]["content"], "beta\n")

    def test_n_files_input_order_preserved(self):
        files = [self._write(f"f{i}.txt", f"line-{i}\n") for i in range(5)]
        r = self._run(*[str(f) for f in files], "--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        # parallel _run_batch may complete out of order; output MUST
        # be re-aligned to input order
        self.assertEqual([d["file_path"] for d in data],
                          [str(f) for f in files])


class TestMissingFileInBatch(_ReadBase):
    def test_one_missing_one_present_per_file_status(self):
        a = self._write("a.txt", "alpha\n")
        b = self.tmp / "nope.txt"   # does not exist
        r = self._run(str(a), str(b), "--json")
        # Non-zero exit signals at least one failure
        self.assertNotEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(len(data), 2)
        self.assertTrue(data[0]["ok"])
        self.assertEqual(data[0]["content"], "alpha\n")
        self.assertFalse(data[1]["ok"])
        self.assertIn("error", data[1])


class TestExitCode(_ReadBase):
    def test_all_succeed_exits_zero(self):
        a = self._write("a.txt", "x")
        b = self._write("b.txt", "y")
        r = self._run(str(a), str(b))
        self.assertEqual(r.returncode, 0)

    def test_any_failure_exits_one(self):
        a = self._write("a.txt", "x")
        r = self._run(str(a), "/nope/missing")
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
