#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen rules-mcp — agent surface for brain-sourced kaizen rules.

Tools:
  rules_list()       → all rules (id, kind, source)
  rules_show(id)     → full rule record (frontmatter + body excerpt)
  rules_validate()   → schema-validate every rule under <brain>/Notes/

Wraps scripts/rules/rules.py — same logic the slash command runs.
Rules live as .md notes in <KAIZEN_BRAIN_DIR>/Notes/ with kaizen:
frontmatter. The plugin reads them at gate-time to apply user-tunable
overrides.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_TARGET = SCRIPT_DIR.parent / "rules" / "rules.py"

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-rules-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-rules")

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
async def rules_list() -> dict:
    """All kaizen rules sourced from <brain>/Notes/. Returns
    {rules: [{id, kind, source_file, applies_to, ...}]}."""
    return await asyncio.to_thread(_run, "list")

@mcp.tool()
async def rules_show(rule_id: str) -> dict:
    """Full record for one rule. `rule_id` is the kaizen-id from
    frontmatter (e.g. `kaizen-allow-log-deletions`).
    Returns the rule's frontmatter dict + body excerpt."""
    return await asyncio.to_thread(_run, "show", rule_id)

@mcp.tool()
async def rules_validate() -> dict:
    """Schema-validate every rule under <brain>/Notes/. Returns
    {valid: int, invalid: int, errors: [{file, message}, ...]}."""
    return await asyncio.to_thread(_run, "validate")

if __name__ == "__main__":
    mcp.run()
