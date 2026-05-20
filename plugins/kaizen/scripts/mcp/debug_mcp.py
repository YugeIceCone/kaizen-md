#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen debug-mcp — agent surface for the debug toolkit.

Tools (read-only / safe verbs only):
  debug_smoke()             exercise every kaizen-* bin with --help
  debug_lint(paths=[...])   static-scan for common bug patterns
  debug_check(axes, path)   parse-validity across python/yaml/jsonl/schema

Deferred (not exposed via MCP):
  scan / parse / tail       interactive or streaming — agent-unfriendly
  replay                    runs arbitrary commands — too broad surface

Wraps scripts/debug.py — same logic kaizen-debug runs.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_TARGET = SCRIPT_DIR.parent / "debug.py"

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-debug-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-debug")

def _run(verb: str, *extra: str) -> dict:
    cmd = ["python3", str(_TARGET), verb, *extra, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode not in (0, 2):
        # rc 2 is normal for smoke when some bins fail; treat as data, not error
        return {"error": (r.stderr or r.stdout or "").strip(), "rc": r.returncode}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"output": r.stdout.strip()}

@mcp.tool()
async def debug_smoke() -> dict:
    """Exercise every kaizen-* bin with `--help`. Returns
    {passed, failed, skipped, results: [{name, ok, rc, error?}]}.

    Interactive / long-running bins (setup, daemon, browser, loop,
    trace-proxy, update, publish, etc.) are skipped per the in-script
    deny-list. Failure = bad rc OR crash-signature in stderr."""
    return await asyncio.to_thread(_run, "smoke")

@mcp.tool()
async def debug_lint(paths: list[str] | None = None) -> dict:
    """Static-scan for common bug patterns (heredoc unbound vars,
    missing bridges, etc.). `paths` defaults to plugin-wide scan.
    Returns {findings: [{file, line, kind, hint}, ...], counts}."""
    extra = tuple(paths) if paths else ()
    return await asyncio.to_thread(_run, "lint", *extra)

@mcp.tool()
async def debug_check(
    axes: list[str] | None = None,
    path: str | None = None,
) -> dict:
    """Parse-validity check per axis. `axes` is any subset of
    ['python', 'yaml', 'jsonl', 'schema'] (default: all four). `path`
    is the scan root (default: plugin root). Returns
    {passed, failed, axes, results: [{axis, file, line, kind, detail}]}.

    Catches bugs like the un-escaped `'` inside a single-quoted YAML
    scalar that silently broke the 2026-05-19 handoff assess."""
    extra: list[str] = []
    for a in (axes or []):
        if a in ("python", "yaml", "jsonl", "schema"):
            extra.append(f"--{a}")
    if path:
        extra.extend(["--path", path])
    return await asyncio.to_thread(_run, "check", *extra)

if __name__ == "__main__":
    mcp.run()
