#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp>=1.0",
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""kaizen onboard-search-mcp — MCP server exposing semantic search over
the project codebase index. FastMCP + async wrappers around
`onboard_index.do_*` helpers.

Sibling of `trace_mcp.py` and `knowledge_mcp.py`. The codebase index
is **project-scoped** (lives at <repo>/.kaizen/onboard.db) rather than
user-global, because codebases differ per project. The MCP server
resolves root via git toplevel + cwd at startup.

Tools:

  onboard_search(query, top_k=10, language="")
    Semantic search over the project's source files. Optional language
    filter (rust, python, typescript, ...).

  onboard_index_status()
    Index health — total files, total sloc, model, last-indexed-ts,
    counts by language.

  onboard_index_run(no_git=False)
    Incremental index pass. Skips unchanged files via sha dedup.

  onboard_get(file_id)
    Fetch one indexed file by SQLite id (snippet included).

  onboard_recent(limit=20, language="")
    Latest N files by mtime — no semantic ranking.

  onboard_raw_errors()
    v1.31.0+ — files that failed at the lossless capture stage
    (unreadable / non-UTF-8). Each row carries a concrete `error`
    reason, replacing the pre-v1.31 opaque error counter.

  onboard_dropped()
    v1.31.0+ — files captured cleanly but the chunker produced no
    kept chunks (e.g. comment-only files). Surfaces the chunk-stage
    counterpart of onboard_raw_errors.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from mcp.server.fastmcp import FastMCP
    import onboard_index as oi  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-onboard-search-mcp: missing dep: {e}\n"
        "Run: /kaizen:onboard index (first run auto-installs deps via uv)\n"
    )
    sys.exit(1)


def _root() -> Path:
    env = os.environ.get("KAIZEN_ONBOARD_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return Path(out) if out else Path.cwd()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


mcp = FastMCP("onboard-search")


@mcp.tool()
async def onboard_search(
    query: str,
    top_k: int = 10,
    language: str = "",
) -> list[dict]:
    """Semantic search over the project's code SQLite index.

    query: natural-language description (e.g. "auth token validation").
    top_k: max results.
    language: optional filter (rust | python | typescript | go | ...).

    Returns list of {score, id, path, language, bytes, sloc, snippet,
    updated_at}. Score is cosine similarity [0, 1]; higher = closer."""
    return oi.do_search(_root(), query, top_k=top_k, language=language or None)


@mcp.tool()
async def onboard_index_status() -> dict:
    """Index health: total files, sloc, bytes, model, dim, counts by
    language. Run first to confirm the index is built + fresh."""
    return oi.do_stats(_root())


@mcp.tool()
async def onboard_index_run(no_git: bool = False) -> dict:
    """Incremental index pass over the project. Skips unchanged files
    via sha dedup; removes stale entries. Returns {new, skipped,
    stale_removed, errors, total, model, db}.

    no_git: bypass `git ls-files` and walk the filesystem with the
    built-in ignore list. Use when not in a git repo."""
    return oi.do_index(_root(), use_git=not no_git)


@mcp.tool()
async def onboard_get(file_id: int) -> dict:
    """Fetch one indexed file record by SQLite id (snippet included)."""
    r = oi.do_get(_root(), file_id)
    return r if r else {"error": f"id={file_id} not found"}


@mcp.tool()
async def onboard_raw_errors() -> list[dict]:
    """List files that failed at the lossless capture stage (read or
    UTF-8 decode failures). v1.31.0+ — replaces the opaque "N errors"
    counter from `onboard_index_status` with concrete reasons.

    Returns [{path, language, error, bytes}]. Empty list when all files
    captured cleanly. Use this BEFORE reasoning about "why isn't this
    file searchable?" — if it's here, it never made it past stage 1."""
    return oi.do_raw_errors(_root())


@mcp.tool()
async def onboard_dropped() -> list[dict]:
    """List files captured cleanly but dropped at chunk stage (no kept
    chunks after comment-strip + normalization). v1.31.0+ — the chunk-
    stage counterpart of `onboard_raw_errors`.

    Returns [{path, language, bytes, sloc_raw, reason}]. Common cause:
    file is 100% comments. Use this to decide whether a missing file
    is genuinely empty-after-clean or a chunker bug worth fixing."""
    return oi.do_dropped(_root())


@mcp.tool()
async def onboard_recent(limit: int = 20, language: str = "") -> list[dict]:
    """Latest N files by mtime — no semantic ranking. Useful for "what
    changed lately in this codebase?" Combine with language filter."""
    root = _root()
    p = oi.db_path(root)
    if not p.is_file():
        return []
    conn = oi.open_db(root, create=False)
    sql = "SELECT id, path, language, bytes, sloc, snippet, updated_at FROM code_files"
    params: list = []
    if language:
        sql += " WHERE language = ?"
        params.append(language)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{k: r[k] for k in r.keys()} for r in rows]


if __name__ == "__main__":
    mcp.run()
