#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
#     "jsonschema>=4.0",
# ]
# ///
"""kaizen iron-laws MCP — query + check the iron-laws registry mid-session.

Wraps the iron-laws single-source-of-truth registry
(`skills/iron-laws/domain/iron-laws.yaml`) so Claude can consult the
laws and run the checker as MCP tools instead of shelling out.

## Tools

  iron_laws_list()
    Every law — id / severity / enforcement / check / statement.

  iron_laws_show(law_id)
    One law's full record. Returns {"error": ...} for an unknown id.

  iron_laws_check(scope="staged", law_id="")
    Run the auto-law checks. scope: "staged" (the staged diff) or
    "all" (whole-plugin audit). law_id restricts to one law.
    Returns {scope, hard, soft, findings: [...]}.

## Spawning

Registered in .mcp.json as `iron-laws`. CC spawns on first
`mcp__plugin_kaizen_iron-laws__*` invocation.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent.parent / "iron-laws" / "application"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(APP_DIR))

try:
    from fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    sys.stderr.write(
        f"kaizen-iron-laws-mcp: missing dep: {e}\n"
        "Ensure mcp>=1.0 is installed (uv handles this automatically).\n"
    )
    sys.exit(1)

import _iron_laws  # noqa: E402
import _loader  # noqa: E402

mcp = FastMCP("kaizen-iron-laws")


@mcp.tool()
async def iron_laws_list() -> list[dict]:
    """Every iron law — id / severity / enforcement / check / statement.

    The registry (skills/iron-laws/domain/iron-laws.yaml) is the single
    source of truth; this returns it schema-validated."""
    return await asyncio.to_thread(_loader.load_laws)


@mcp.tool()
async def iron_laws_show(law_id: str) -> dict:
    """One law's full record. Returns {"error": ...} for an unknown id."""
    law = await asyncio.to_thread(_loader.get_law, law_id)
    if law is None:
        return {"error": f"no law with id '{law_id}'"}
    return law


@mcp.tool()
async def iron_laws_check(scope: str = "staged", law_id: str = "") -> dict:
    """Run the auto-law checks.

    scope:  "staged" (the staged git diff — the pre-commit gate's mode)
            or "all" (whole-plugin audit).
    law_id: restrict to one law's check (empty = all auto laws).

    Returns {scope, hard, soft, findings: [{law_id, severity, message,
    path, detail}, ...]}."""
    findings = await asyncio.to_thread(
        _iron_laws.run_checks, scope, None, law_id or None
    )
    hard = sum(1 for f in findings if f.severity == "hard")
    return {
        "scope": scope,
        "hard": hard,
        "soft": len(findings) - hard,
        "findings": [asdict(f) for f in findings],
    }


if __name__ == "__main__":
    mcp.run()
