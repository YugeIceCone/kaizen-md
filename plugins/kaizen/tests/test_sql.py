"""sql (idea #201): DuckDB wrapper for ad-hoc queries over JSONL.
Graceful-skip when duckdb not installed."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_KZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_KZ / "scripts/io"))

import sql as kz_sql  # noqa: E402


class TestSql(unittest.TestCase):
    def test_is_available_is_bool(self):
        self.assertIsInstance(kz_sql.is_available(), bool)

    def test_query_unavailable_graceful(self):
        if kz_sql.is_available():
            self.skipTest("duckdb installed; can't test fallback")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.jsonl"
            p.write_text(json.dumps({"id": 1}) + "\n")
            res = kz_sql.query(f'SELECT * FROM "{p}"')
            self.assertFalse(res["available"])
            self.assertEqual(res["rows"], [])

    def test_query_when_available(self):
        if not kz_sql.is_available():
            self.skipTest("duckdb not installed")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.jsonl"
            p.write_text(json.dumps({"id": 1, "n": 5}) + "\n"
                          + json.dumps({"id": 2, "n": 7}) + "\n")
            res = kz_sql.query(f'SELECT SUM(n) AS total FROM "{p}"')
            self.assertTrue(res["available"])
            self.assertEqual(res["rows"][0]["total"], 12)


if __name__ == "__main__":
    unittest.main()
