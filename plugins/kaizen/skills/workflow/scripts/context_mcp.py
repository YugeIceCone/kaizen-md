#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP server — exposes context-window state as MCP tools.

Wraps the per-call `context.py` helpers so agents can query the current
context-window state structurally (vs subprocess-via-Bash with stdout
parsing). Sister to `/kaizen:context` slash.

Tools:
  context_status() → {tokens, limit, pct, zone, recommendation}
      Headline tool. Reads env / stdin / session-JSONL per the same
      precedence as the slash; returns parseable dict.

Design — same as backlog_mcp / brain_mcp:
  - Imports context.py helpers directly (no subprocess).
  - Returns dict (FastMCP serializes to JSON for the client).
  - When tokens unknown, zone='unknown' + recommendation explains.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastmcp import FastMCP

_HERE = Path(os.path.realpath(__file__)).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import context as _ctx  # noqa: E402


mcp = FastMCP("context")


_RECS = {
    "green":  "OK to continue current work.",
    "yellow": "Approaching context limit — wrap-up tasks, avoid long reads.",
    "red":    "Near context limit — handoff or /compact now.",
    "unknown": "No CLAUDE_CONTEXT_TOKENS env, no stdin JSON, no active session JSONL.",
}


def context_status() -> dict:
    """Report Claude Code's current context-window state.

    Returns a dict with tokens / limit / pct / zone / recommendation.
    Precedence for the token count (highest first):
      1. CLAUDE_CONTEXT_TOKENS env var (set by hooks/statusline)
      2. Active session JSONL peak (read via context.py helpers)

    Returns:
      dict with keys: tokens (int|None), limit (int), pct (int|None),
                      zone ('green'|'yellow'|'red'|'unknown'),
                      recommendation (str).
    """
    tokens = _ctx.get_tokens("")
    if tokens is None:
        tokens = _ctx.get_tokens_from_jsonl()
    limit = _ctx.get_limit()
    pct = (tokens * 100 // limit) if (tokens is not None and limit) else None
    zone = _ctx.zone_of(pct) if pct is not None else "unknown"
    return {
        "tokens":         tokens,
        "limit":          limit,
        "pct":            pct,
        "zone":           zone,
        "recommendation": _RECS.get(zone, _RECS["unknown"]),
    }


mcp.tool()(context_status)


if __name__ == "__main__":
    mcp.run()
