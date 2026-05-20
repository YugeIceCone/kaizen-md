#!/usr/bin/env -S uv run --script
# consolidated-cli-parent: tokens
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "fastmcp>=3.0",
#   "tree-sitter>=0.23",
#   "tree-sitter-rust>=0.23",
#   "tree-sitter-python>=0.23",
# ]
# ///
"""kaizen-tokens MCP server — positional token addressing over FastMCP.

Sibling of `kaizen-tokens` CLI (scripts/index/tokens.py).
Wraps the same TokenDB store and exposes:

Tools (compact-args agent surface, per spec V9):
  read_token(file_id, slot=0)                       → envelope
  read_token_by_name(file_id, kind, name, parent="") → envelope
  batch_read(tokens=[[fid, slot], ...])             → [envelope]
  list_files()                                       → [{file_id, path, ...}]

Resources:
  mcp://kaizen-tokens/{repo}/tokens  → {"files": [...]}  (file directory)

The strict `bin-wrapper-per-cli` iron-law is satisfied by the
`# consolidated-cli-parent: tokens` header (the wrapper requirement
transfers to `bin/kaizen-tokens` which already exists).
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
# MIGRATION BRIDGE — _token_db still at skills/workflow/scripts/
_LEGACY = _HERE.parents[1] / "skills" / "workflow" / "scripts"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

from _token_db import TokenDB  # noqa: E402


mcp = FastMCP("kaizen-tokens")


# ─── Discovery helpers (V3 — KAIZEN_PROJECT_ROOT_OVERRIDE + .git walk) ──


def _project_root() -> Path:
    override = os.environ.get("KAIZEN_PROJECT_ROOT_OVERRIDE")
    if override:
        return Path(override)
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return Path.cwd()


def _db() -> TokenDB:
    db = TokenDB(_project_root() / ".kaizen" / "token-map.db")
    db.init_schema()
    return db


def _repo_slug() -> str:
    """V35 — repo slug embedded in resource URIs for multi-repo agents."""
    return _project_root().name


def _envelope(file_id: int, slot: int) -> dict:
    """Common envelope builder — shared by every read_* tool + resource.

    Reads body from inlined blob when present; otherwise re-reads the
    file from disk and slices by byte offsets (V19 — large slots).
    """
    db = _db()
    row = db.get_slot(file_id, slot)
    if row is None:
        return {"error": f"slot {slot} of file {file_id} not found"}
    fr = db.conn.execute(
        "SELECT path, version FROM files WHERE file_id=?", (file_id,)
    ).fetchone()
    if fr is None:
        return {"error": f"file_id {file_id} unknown"}

    body = row["body"]
    if body is None:
        try:
            full = (_project_root() / fr["path"]).read_bytes()
            body = full[row["byte_start"]:row["byte_end"]]
        except OSError as exc:
            return {"error": f"cannot read {fr['path']}: {exc}"}

    return {
        "uri":          f"mcp://kaizen-tokens/{_repo_slug()}/{file_id}/{slot}",
        "file_id":      file_id,
        "slot":         slot,
        "kind":         row["kind"],
        "name":         row["name"],
        "parent":       row["parent_qualifier"],
        "path":         fr["path"],
        "version":      fr["version"],
        "content_hash": row["content_hash"],
        "tombstoned":   bool(row["tombstoned"]),
        "body":         body.decode("utf-8", errors="replace"),
    }


# ─── Tool wrappers (V9 — compact-args agent surface) ────────────────────


@mcp.tool()
def read_token(file_id: int, slot: int = 0) -> dict:
    """Read a token by positional address.

    Slot 0 is always the whole file body; slot 1 is the path string;
    slots 2..N are AST top-level items (functions / structs / classes).
    """
    return _envelope(file_id, slot)


@mcp.tool()
def read_token_by_name(file_id: int, kind: str, name: str,
                        parent: str = "") -> dict:
    """V7/V32 — name-stable addressing.

    Survives positional drift across edits. `parent` is the enclosing
    qualifier (e.g. class name for a method); empty string for top-level.
    """
    db = _db()
    slot = db.lookup_by_name(file_id, kind=kind, name=name, parent=parent)
    if slot is None:
        return {
            "error": (
                f"no slot for kind={kind!r} name={name!r} "
                f"parent={parent!r} in file_id={file_id}"
            )
        }
    return _envelope(file_id, slot)


@mcp.tool()
def batch_read(tokens: list[list[int]]) -> list[dict]:
    """Read multiple (file_id, slot) pairs in one round-trip (V9 batch)."""
    return [_envelope(int(fid), int(slot)) for fid, slot in tokens]


@mcp.tool()
def list_files() -> list[dict]:
    """List indexed files — file_id ↔ path directory for the active repo."""
    db = _db()
    rows = db.conn.execute(
        "SELECT file_id, path, language, version "
        "FROM files WHERE path_gone=0 ORDER BY file_id"
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Resources (file directory) ─────────────────────────────────────────


@mcp.resource("mcp://kaizen-tokens/{repo}/tokens")
def resource_tokens_directory(repo: str) -> dict:
    """Directory of file_id ↔ path mappings for the named repo.

    Note: `repo` is templated but currently honored implicitly via the
    active repo's `_project_root()`. A future multi-repo extension can
    switch on this parameter.
    """
    return {"files": list_files()}


# ─── --self-test (for unit tests; bypasses stdio MCP loop) ──────────────


def _self_test() -> int:
    """Probe the FastMCP instance and emit a JSON summary on stdout.

    Used by tests/test_tokens_mcp.py to verify tool registration without
    importing fastmcp into the test interpreter.
    """
    import asyncio

    async def _gather():
        tools = await mcp.list_tools()
        names = sorted(getattr(t, "name", str(t)) for t in tools)
        return names

    try:
        names = asyncio.run(_gather())
        report = {
            "ok":          True,
            "server_name": "kaizen-tokens",
            "tools":       names,
            "count":       len(names),
        }
    except Exception as exc:  # pragma: no cover — defensive
        report = {"ok": False, "error": repr(exc)}
        print(json.dumps(report))
        return 1

    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    mcp.run()
