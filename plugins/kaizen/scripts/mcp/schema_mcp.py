#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen schema-mcp — agent surface for declarative workflow schemas.

Tools:
  schema_list()                → all schemas across project/user/built-in tiers
  schema_show(name)            → full schema dict
  schema_stages(name)          → topo-ordered stage ids
  schema_artifact(name, id)    → one artifact's dict (description + template + requires)
  schema_branches(name, id)    → branch_high/medium/low alternative-path stage lists
  schema_validate(name)        → structural + DAG validation

Wraps scripts/workflow/workflow_runner.py — same logic /kaizen:schema runs.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_TARGET = SCRIPT_DIR.parent / "workflow" / "workflow_runner.py"

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-schema-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-schema")

def _run(*args: str) -> dict:
    """Invoke workflow_runner. Most verbs emit JSON natively (`show`,
    `branches`, `artifact`); `list` + `stages` emit text — return raw."""
    cmd = ["python3", str(_TARGET), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout or "").strip(), "rc": r.returncode}
    out = r.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"output": out}

@mcp.tool()
async def schema_list() -> dict:
    """All schemas — project (`<repo>/.kaizen/workflow/schemas/`),
    user (`~/.claude/.kaizen/schemas/`), and plugin built-ins.
    Returns {schemas: [{name, tier, path}, ...]}."""
    result = await asyncio.to_thread(_run, "list")
    if "output" in result:
        # Parse text format: "  <name>   [tier] <path>"
        items = []
        for line in result["output"].splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[1].startswith("["):
                items.append({"name": parts[0], "tier": parts[1].strip("[]"), "path": parts[2]})
        return {"schemas": items}
    return result

@mcp.tool()
async def schema_show(name: str) -> dict:
    """Full parsed schema as JSON — name, version, description, artifacts,
    apply block."""
    return await asyncio.to_thread(_run, "show", name)

@mcp.tool()
async def schema_stages(name: str) -> dict:
    """Topo-ordered stage ids — what workflow.sh consumes. Returns
    {stages: [...]}."""
    result = await asyncio.to_thread(_run, "stages", name)
    if "output" in result:
        return {"stages": [s for s in result["output"].splitlines() if s.strip()]}
    return result

@mcp.tool()
async def schema_artifact(name: str, artifact_id: str) -> dict:
    """One artifact's full dict — id, generates, template, requires,
    description, branches."""
    return await asyncio.to_thread(_run, "artifact", name, artifact_id)

@mcp.tool()
async def schema_branches(name: str, artifact_id: str) -> dict:
    """Branch_high / medium / low alternative-path stage lists for an
    artifact. Used by an agent to plan after completing the artifact
    (e.g. design.md) based on its Confidence Score."""
    return await asyncio.to_thread(_run, "branches", name, artifact_id)

@mcp.tool()
async def schema_validate(name: str) -> dict:
    """Structural + DAG validation. Returns {valid: bool, errors: [...]}."""
    result = await asyncio.to_thread(_run, "validate", name)
    # validate exits non-zero on errors; _run captures that
    if "error" in result and "rc" in result:
        return {"valid": False, "errors": [result["error"]]}
    return {"valid": True, "errors": []}

if __name__ == "__main__":
    mcp.run()
