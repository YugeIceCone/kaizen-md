#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0", "pyyaml>=6.0"]
# ///
"""kaizen axis-runner-mcp — agent surface for the declarative axis runner.

Tools:
  list_axes()        → ["reference-demo", ...] (stems under domain/axes/)
  run_axis(name)     → canonical envelope from running one axis
  report(name)       → alias for run_axis (mirrors coverage_mcp shape)

Wraps `scripts/quality/axis_runner.py` — same logic the
`kaizen-axis-runner` CLI runs. Mirrors `coverage_mcp.py` shape: one
small subprocess wrapper per verb, JSON in / JSON out.

Refs: /tmp/axis-runner.blueprint.json item-08.6, item-07
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "quality" / "axis_runner.py"
)

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-axis-runner-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-axis-runner")


def _run_cli(*args: str) -> dict:
    cmd = ["python3", str(_SCRIPT), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and not r.stdout:
        return {"error": (r.stderr or "").strip(), "rc": r.returncode}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"output": r.stdout.strip(), "rc": r.returncode}


@mcp.tool()
async def list_axes() -> dict:
    """List declarative axis YAML stems under skills/workflow/domain/axes/.
    Returns the canonical envelope with `data.axes: [...]`."""
    return await asyncio.to_thread(_run_cli, "list")


@mcp.tool()
async def run_axis(name: str) -> dict:
    """Run one declarative axis by name (stem or absolute path). Returns
    the canonical envelope with `data.axis`, `data.findings`, `verdict`
    and `counts.findings`."""
    return await asyncio.to_thread(_run_cli, "run", "--axis", name)


@mcp.tool()
async def report(name: str) -> dict:
    """Alias for run_axis — kept for parity with the report/gaps verb
    convention used by other kaizen quality MCPs."""
    return await asyncio.to_thread(_run_cli, "report", "--axis", name)


if __name__ == "__main__":
    mcp.run()
