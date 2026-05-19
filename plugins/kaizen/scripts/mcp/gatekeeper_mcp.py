#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
#     "jsonschema>=4.0",
# ]
# ///
"""kaizen gatekeeper MCP — run the unified gate as an MCP tool.

Wraps `gatekeeper.py` so Claude can run the gate mid-session without
shelling out. The gate aggregates iron-laws + efficient-tool-use
anti-patterns + karpathy diff-level scanners + plugin-validator into a
single structured verdict.

## Tools

  gatekeeper_check(scope="staged", only=None)
    Run all (or one) sub-gates. scope: "staged" (the staged diff)
    or "all" (whole-plugin audit). only: limit to one sub-gate
    (iron-laws | etu | karpathy | validator); None runs all.
    Returns {overall, counts, durations_ms, findings: [...]}.

  gatekeeper_list()
    Enumerate the sub-gates the gatekeeper composes.

## Spawning

Mounted into the kaizen gateway via `gateway.py::SUBSERVERS`. Reachable
as `mcp__plugin_kaizen_kaizen__gatekeeper_check(...)` once the gateway
spawns.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Explicit file-path module load — gatekeeper.py + etu_scan + _iron_laws
# all ship loaders that collide on bare `import _loader`. The gatekeeper
# itself handles this internally; we just need to load the gatekeeper
# module without sys.path pollution.


def _load_gatekeeper():
    spec = importlib.util.spec_from_file_location(
        "kaizen_gatekeeper_mcp_inner", SCRIPT_DIR.parents[1] / "skills" / "workflow" / "scripts" / "gatekeeper.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load gatekeeper.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kaizen_gatekeeper_mcp_inner"] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    from fastmcp import FastMCP
except ImportError:
    sys.stderr.write("kaizen-gatekeeper-mcp: fastmcp>=3.0 required\n")
    sys.exit(2)


mcp = FastMCP("kaizen-gatekeeper")


@mcp.tool()
async def gatekeeper_check(scope: str = "staged",
                           only: str | None = None) -> dict:
    """Run the unified kaizen gate. Aggregates iron-laws + etu (shell
    anti-patterns) + karpathy diff-level scanners + plugin-validator.

    Args:
      scope: "staged" (default — pre-commit-equivalent) or "all" (full audit).
      only:  restrict to one sub-gate (iron-laws | etu | karpathy | validator).
             None runs every sub-gate.

    Returns:
      {
        "overall": "green" | "yellow" | "red",
        "counts": {"error": N, "warn": N, "info": N},
        "durations_ms": {"iron-laws": N, "etu": N, ...},
        "findings": [
          {"gate": ..., "severity": ..., "rule_id": ..., "message": ...,
           "file": ..., "line": N|null},
          ...
        ]
      }
    """
    if scope not in ("staged", "all"):
        return {"error": f"scope must be 'staged' or 'all', got: {scope!r}"}

    def _run():
        gk = _load_gatekeeper()
        if only is not None and only not in gk.SUB_GATES:
            return {"error": f"unknown sub-gate: {only!r}",
                    "available": list(gk.SUB_GATES.keys())}
        v = gk.gate_all(scope=scope, only=only)
        return {
            "overall": v.overall,
            "counts": v.counts,
            "durations_ms": v.durations_ms,
            "findings": [asdict(f) for f in v.findings],
        }

    return await asyncio.to_thread(_run)


@mcp.tool()
async def gatekeeper_list() -> dict:
    """Enumerate the sub-gates the gatekeeper composes.

    Returns:
      {"sub_gates": ["iron-laws", "etu", "karpathy", "validator"]}
    """
    def _run():
        gk = _load_gatekeeper()
        return {"sub_gates": list(gk.SUB_GATES.keys())}

    return await asyncio.to_thread(_run)


if __name__ == "__main__":
    mcp.run()
