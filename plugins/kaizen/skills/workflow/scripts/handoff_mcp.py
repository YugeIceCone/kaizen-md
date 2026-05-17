#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP server — read-mostly handoff queries.

Sister to `/kaizen:handoff`. Exposes the queryable surface (latest,
list, path) so agents can query the handoff store without subprocess
roundtrip + JSON parsing.

Write ops (create/scaffold/auto-finalize/verify) stay slash-driven —
they're high-stakes (write YAML + index + emit assess decision) and
benefit from the slash body's instructional context.

Tools:
  handoff_latest(limit=1)        → {handoffs: [...]}
  handoff_list(limit=20, session=None) → {handoffs: [...]}
  handoff_path()                  → {db_path, yaml_dir}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

_HERE = Path(os.path.realpath(__file__)).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _handoff as _ho  # noqa: E402


mcp = FastMCP("handoff")


def handoff_latest(limit: int = 1) -> dict:
    """The most-recent handoff(s) — full content included.

    Args:
      limit: how many recent handoffs to return (newest first). Default 1.

    Returns:
      dict with `handoff` (single dict when limit=1, may be None when
      store empty) AND `handoffs` (full list, always a list).
    """
    rows = _ho.latest_handoffs(limit=limit)
    return {
        "handoff":  rows[0] if rows else None,
        "handoffs": rows,
    }


def handoff_list(limit: int = 20, session_id: Optional[str] = None) -> dict:
    """Recent handoffs (metadata only — no `content` field).

    Args:
      limit: max number to return. Default 20.
      session_id: optional filter — only handoffs pinned to this session.

    Returns:
      dict with `handoffs` (list of metadata-only dicts).
    """
    rows = _ho.list_handoffs(limit=limit, session_id=session_id)
    return {"handoffs": rows}


def handoff_path() -> dict:
    """Resolved paths for the handoff store + YAML dir.

    Returns:
      dict with `db_path` (handoff.db) + `yaml_dir` (the dir holding
      per-session YAML files).
    """
    return {
        "db_path":  str(_ho.handoff_db_path()),
        "yaml_dir": str(_ho.handoffs_dir()),
    }


mcp.tool()(handoff_latest)
mcp.tool()(handoff_list)
mcp.tool()(handoff_path)


if __name__ == "__main__":
    mcp.run()
