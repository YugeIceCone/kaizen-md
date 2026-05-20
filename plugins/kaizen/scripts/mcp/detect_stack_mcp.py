#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP server — exposes stack-detection as MCP tools.

Wraps detect_stack.py helpers so install / dispatch / setup-menu flows
can query the project's stack without subprocess scraping. Sister to
`/kaizen:detect-stack`.

Tools:
  detect_stack_show()  → dict | None   (read .agents/stack-context.json)
  detect_stack_path()  → {json_path, md_path}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastmcp import FastMCP

_HERE = Path(os.path.realpath(__file__)).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import detect_stack as _ds  # noqa: E402

mcp = FastMCP("detect_stack")

def detect_stack_show() -> dict | None:
    """Read the existing stack-context.json artifact.

    Returns:
      dict (the parsed artifact) if `.agents/stack-context.json` exists
      and parses cleanly. None when the artifact is absent — callers
      should treat that as "run a fresh scan".
    """
    json_path = _ds._output_path_json()
    if not json_path.is_file():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

def detect_stack_path() -> dict:
    """Return the resolved artifact paths (json + md).

    Returns:
      dict with `json_path` + `md_path` (both string paths). Useful
      for callers that want to read the artifact themselves vs go
      through detect_stack_show.
    """
    return {
        "json_path": str(_ds._output_path_json()),
        "md_path":   str(_ds._output_path_md()),
    }

mcp.tool()(detect_stack_show)
mcp.tool()(detect_stack_path)

if __name__ == "__main__":
    mcp.run()
