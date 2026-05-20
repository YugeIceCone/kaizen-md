#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen surface-mcp — agent surface for the plugin inventory.

Tools:
  surface_list()      → counts + MCP servers + hooks lists
  surface_validate()  → consistency check (drift between gateway / hooks.json / .mcp.json)

Wraps scripts/iron-laws/surface.py — same logic /kaizen:surface runs.
Use to let agents self-orient: what MCP servers / hooks / sub-tools
exist in this plugin install, before deciding which to call.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_TARGET = SCRIPT_DIR.parent / "iron-laws" / "surface.py"

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-surface-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-surface")

def _run(verb: str, *extra: str) -> dict:
    cmd = ["python3", str(_TARGET), verb, *extra, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout or "").strip(), "rc": r.returncode}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"output": r.stdout.strip()}

@mcp.tool()
async def surface_list() -> dict:
    """Plugin surface inventory:
      - mcp_servers: [{name, module, path, tool_count, in_core}, ...]
      - hooks:       [{event, command, ...}, ...]
      - counts:      {mcp_servers, hooks}

    Use to let an agent self-orient before reaching for a tool."""
    return await asyncio.to_thread(_run, "list")

@mcp.tool()
async def surface_validate() -> dict:
    """Consistency check across the registries. Findings:
      - MCP module exists on disk but not declared in gateway SUBSERVERS
      - hook script declared in hooks.json but missing from hooks/claude/
      - hook script in hooks/claude/ but not declared in hooks.json
      - plugin.json missing permissions for an MCP/hook entry

    Returns {findings: [{severity, kind, target, message}, ...]}."""
    return await asyncio.to_thread(_run, "validate")

if __name__ == "__main__":
    mcp.run()
