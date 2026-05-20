#!/usr/bin/env python3
"""kaizen-sql — DuckDB wrapper for ad-hoc queries over JSONL files.

Referenced from CLAUDE.md's JSONL pattern: jq for simple filters,
DuckDB for joins / aggregates / multi-file unions.

Example:
  kaizen-sql 'SELECT bucket, COUNT(*) FROM "plans/*.jsonl" GROUP BY bucket'

Optional dep — `is_available()` returns False when duckdb isn't
installed. The CLI prints an install hint when unavailable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-sql", tool_version="1.0.0")

def is_available() -> bool:
    try:
        import duckdb  # noqa: F401
        return True
    except ImportError:
        return False

def query(sql: str, *, limit: int | None = None) -> dict:
    if not is_available():
        return {"available": False, "rows": [], "columns": [],
                "note": "duckdb not installed — `pip install duckdb`"}
    import duckdb
    con = duckdb.connect()
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        raw = cur.fetchall()
        if limit is not None:
            raw = raw[:limit]
        rows = [dict(zip(cols, r)) for r in raw]
        return {"available": True, "rows": rows, "columns": cols}
    finally:
        con.close()

def _cmd_query(args) -> int:
    res = query(args.sql, limit=args.limit)
    if not res["available"]:
        if args.json:
            _emit(res, verdict="yellow")
        else:
            print(res.get("note", "duckdb unavailable"), file=sys.stderr)
        return 0 if args.json else 1
    if args.json:
        _emit({"sql": args.sql, "rows": res["rows"],
                "columns": res["columns"], "count": len(res["rows"])},
              verdict="green", counts={"rows": len(res["rows"])})
    else:
        for r in res["rows"]:
            print(json.dumps(r, default=str))
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-sql",
        description="DuckDB ad-hoc query CLI over JSONL files.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query", help="Run a SQL query (positional or stdin).")
    q.add_argument("sql")
    q.add_argument("--limit", type=int, default=None)
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=_cmd_query)
    args = ap.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
