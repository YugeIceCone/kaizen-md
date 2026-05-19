#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen coverage-mcp — agent surface for `/kaizen:coverage`.

Tools:
  coverage_gaps()    → list of script stems with no matching test
  coverage_summary() → {covered, uncovered, total, gap_count}
  coverage_report()  → full 1:1 mapping (slow on large repos)

Wraps scripts/quality/coverage.py — same logic the slash command runs.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_TARGET = SCRIPT_DIR.parent / "quality" / "coverage.py"

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-coverage-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-coverage")


def _run(verb: str, *extra: str, want_json: bool = True) -> dict:
    cmd = ["python3", str(_TARGET), verb, *extra]
    if want_json:
        cmd.append("--json")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout or "").strip(), "rc": r.returncode}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"output": r.stdout.strip()}


@mcp.tool()
async def coverage_gaps() -> dict:
    """Script stems under skills/workflow/scripts that have no matching
    test in tests/. Returns {uncovered: [...]} sorted by name."""
    return await asyncio.to_thread(_run, "gaps")


@mcp.tool()
async def coverage_summary() -> dict:
    """Coverage summary: {covered: int, uncovered: int, total: int,
    gap_count: int} — counts only, no individual file list."""
    return await asyncio.to_thread(_run, "summary")


@mcp.tool()
async def coverage_report() -> dict:
    """Full 1:1 mapping: per-source-script → [matching test files].
    Heavier than `gaps` — use when you want the full report.
    Returns {mapping: {script: [tests, ...]}, total_scripts, total_tests}."""
    return await asyncio.to_thread(_run, "report")


if __name__ == "__main__":
    mcp.run()
