#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen MCP server — exposes the backlog as MCP tools via fastmcp.

Wraps backlog.py subcommands as MCP tools so any MCP client (Claude Desktop,
Inspector, other agents) can list/add/start/tick/park/decision the backlog
programmatically.

Run standalone (stdio transport):
    uv run --script backlog_mcp.py

The plugin's `.mcp.json` wires this server automatically when the plugin
is installed; no manual start needed.

Design:
    - Every tool is a thin shell-out to the sibling `backlog.py`.
    - We never re-implement backlog logic — single source of truth.
    - Returns the CLI stdout verbatim so MCP clients see what humans see.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP

SCRIPT_DIR = Path(os.path.realpath(__file__)).parent
BACKLOG_PY = SCRIPT_DIR / "backlog.py"


def _run(*args: str) -> str:
    """Invoke backlog.py with args; return stdout (or stderr on failure)."""
    if not BACKLOG_PY.exists():
        return f"error: backlog.py not found at {BACKLOG_PY}"
    result = subprocess.run(
        ["python3", str(BACKLOG_PY), *args],
        capture_output=True,
        text=True,
    )
    return result.stdout or result.stderr or ""


mcp = FastMCP("backlog")


@mcp.tool()
def list_items(section: str = "all") -> str:
    """List backlog items.

    Args:
        section: one of `in_flight`, `next_up`, `done`, `parked`, `all` (default).
    """
    return _run("list", section)


@mcp.tool()
def show(item_id: str) -> str:
    """Show one backlog item as JSON.

    Args:
        item_id: e.g. `BK-001`
    """
    return _run("show", item_id)


@mcp.tool()
def add(
    title: str,
    probe: str,
    verify: str,
    section: str = "next_up",
    ref: str | None = None,
    tags: str | None = None,
) -> str:
    """Add a new backlog item.

    Args:
        title: verb-first description (e.g. "Wire find_references via LSP-backed analyzer")
        probe: trace/grep/sem command proving the item stays micro (≤3 files, no manifest edits)
        verify: command proving the work is done (cargo test ..., make t, ...)
        section: `in_flight` | `next_up` | `done` | `parked` (default: `next_up`)
        ref: optional source citation (e.g. "handoff §lim 4")
        tags: comma-separated tags (e.g. "observability,lsp")
    """
    args = ["add", "--title", title, "--probe", probe, "--verify", verify, "--section", section]
    if ref:
        args += ["--ref", ref]
    if tags:
        args += ["--tags", tags]
    return _run(*args)


@mcp.tool()
def start(item_id: str) -> str:
    """Move a backlog item from `next_up` to `in_flight` (timestamps started_at).

    Args:
        item_id: e.g. `BK-001`
    """
    return _run("start", item_id)


@mcp.tool()
def tick(item_id: str, committed: str | None = None) -> str:
    """Move a backlog item from `in_flight` to `done` (timestamps committed_at).

    Args:
        item_id: e.g. `BK-001`
        committed: optional short SHA of the commit that landed the work
    """
    args = ["tick", item_id]
    if committed:
        args += ["--committed", committed]
    return _run(*args)


@mcp.tool()
def park(item_id: str, reason: str) -> str:
    """Move a backlog item to `parked` with a reason.

    Args:
        item_id: e.g. `BK-001`
        reason: short string explaining why it's deferred
    """
    return _run("park", item_id, "--reason", reason)


@mcp.tool()
def unpark(item_id: str, section: str = "next_up") -> str:
    """Move a backlog item out of `parked` into `next_up` (or specified section).

    Args:
        item_id: e.g. `BK-001`
        section: target section, default `next_up`
    """
    return _run("unpark", item_id, "--section", section)


@mcp.tool()
def decision(text: str, why: str | None = None) -> str:
    """Append a decision (one-liner mini-ADR) to the backlog.

    Args:
        text: the decision (e.g. "Backlog.json adopted as source of truth")
        why: optional rationale
    """
    args = ["decision", "--text", text]
    if why:
        args += ["--why", why]
    return _run(*args)


@mcp.tool()
def render() -> str:
    """Regenerate the backlog.md view from backlog.json. Idempotent."""
    return _run("render")


@mcp.tool()
def verify() -> str:
    """Verify backlog.md matches backlog.json (CI drift check). Exits non-zero on drift."""
    return _run("verify")


if __name__ == "__main__":
    mcp.run()
