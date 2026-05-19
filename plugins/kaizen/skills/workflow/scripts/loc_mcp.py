#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen loc-mcp — MCP server exposing function-level codebase metrics
and per-symbol search over the kaizen `loc.db` SQLite index.

Sibling of `knowledge_mcp.py`. FastMCP + async wrappers around
`loc_index.py` data-returning helpers (do_*).

Tools (Claude can invoke):

  loc_search(name, qualified, kind, language, min_lines, max_lines,
             complexity, no_tests, only_tests, god, top_k)
    Structured symbol search. Supports glob in `name` (e.g. '*carve*').

  loc_function_at(file, line)
    Return the symbol(s) enclosing <file>:<line>. Innermost match first.

  loc_god_symbols(tier="critical", top_k=20)
    Symbols inside god-tier files (>500 or >1000 lines).

  loc_stats(by="")
    Index stats. `by` may be "language" or "kind" for grouped counts.

  loc_files(god, language, comment_density, max_fn_lines, top_k)
    File-level search.

  loc_show(symbol_id)
    Fetch one symbol + extract its source via byte range.

  loc_index_run(root="")
    Run an incremental index pass. Returns counts dict.

## State

Per-repo SQLite at `<repo>/.kaizen/loc.db`. Shared with the `kaizen-loc`
CLI / slash command. MCP server resolves the repo root via the cwd
the server is spawned in (Claude Code spawns from the project dir).

## Spawning

Registered in `.mcp.json` as `kaizen-loc`. Claude Code spawns on-demand
when the first `mcp__plugin_kaizen_kaizen-loc__*` tool fires.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — until indexers move back / consumers move forward
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "indexers"))

try:
    from fastmcp import FastMCP
    import loc_index as li  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-loc-mcp: missing dep: {e}\n"
        "Run: /kaizen:loc index (first run auto-installs deps via uv)\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-loc")


def _resolve_root() -> Path:
    """Repo root via git rev-parse, else cwd. MCP server inherits cwd
    from the Claude Code project that spawned it."""
    env = os.environ.get("KAIZEN_LOC_ROOT")
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


@mcp.tool()
async def loc_search(
    name: str = "",
    qualified: str = "",
    kind: str = "",
    language: str = "",
    min_lines: int = 0,
    max_lines: int = 0,
    complexity: str = "",
    no_tests: bool = False,
    only_tests: bool = False,
    god: str = "",
    top_k: int = 50,
) -> list[dict]:
    """Structured symbol search.

    name: substring or glob (e.g. '*carve*'). Empty = any.
    qualified: substring of qualified_name (e.g. 'CodexExporter.export_skills').
    kind: function | method | class | async-function | static-method | ...
    language: Python | Rust | TypeScript | ...
    min_lines/max_lines: filter by physical line range.
    complexity: comparison string '>=15' / '<5' / '==1'.
    no_tests: exclude test symbols.
    only_tests: only test symbols.
    god: 'critical' | 'warning' — restrict to god-file symbols.
    top_k: max results (default 50).

    Returns symbol-row dicts ordered by physical_lines DESC."""
    return li.do_search(
        _resolve_root(),
        name=name or None,
        qualified=qualified or None,
        kind=kind or None,
        language=language or None,
        min_lines=min_lines or None,
        max_lines=max_lines or None,
        complexity=complexity or None,
        no_tests=no_tests,
        only_tests=only_tests,
        god=god or None,
        limit=top_k,
    )


@mcp.tool()
async def loc_function_at(file: str, line: int) -> list[dict]:
    """Return the symbol(s) enclosing <file>:<line>. Smallest (innermost)
    match first. `file` may be a relative path; matches by suffix.

    Use this when you have a stack trace or a citation like
    'crates/agent/src/borg_loop/mod.rs:412' and want to know which
    function owns that line."""
    return li.do_search(
        _resolve_root(),
        at=f"{file}:{line}",
        limit=10,
    )


@mcp.tool()
async def loc_god_symbols(tier: str = "critical", top_k: int = 20) -> list[dict]:
    """Symbols inside god-tier files. `tier` = 'critical' (>1000 lines) or
    'warning' (500–1000 lines). Sorted by symbol physical_lines DESC.

    Use to triage the largest functions in the worst files first."""
    return li.do_search(_resolve_root(), god=tier, limit=top_k)


@mcp.tool()
async def loc_stats(by: str = "") -> dict:
    """Index health + grouped counts.

    by: '' (default — just totals), 'language', or 'kind'."""
    return li.do_stats(_resolve_root(), by=by or None)


@mcp.tool()
async def loc_files(
    god: str = "",
    language: str = "",
    comment_density: str = "",
    max_fn_lines: str = "",
    top_k: int = 50,
) -> list[dict]:
    """File-level search.

    god: 'critical' | 'warning'.
    language: 'Python' | 'Rust' | ...
    comment_density: comparison '<0.05' (5% — sparse).
    max_fn_lines: comparison '>200' (file contains a 200+ line function).

    Returns file-row dicts ordered by physical_lines DESC."""
    return li.do_files(
        _resolve_root(),
        god=god or None,
        language=language or None,
        comment_density=comment_density or None,
        max_fn_lines=max_fn_lines or None,
        limit=top_k,
    )


@mcp.tool()
async def loc_show(symbol_id: int) -> dict:
    """Fetch one symbol record + extract its source via byte range.
    `symbol_id` comes from `loc_search` results (`id` field).

    Returns the symbol dict with an added `source` field (or `null` if
    the file was deleted / moved since indexing)."""
    r = li.do_show(_resolve_root(), symbol_id)
    return r if r else {"error": f"id={symbol_id} not found"}


@mcp.tool()
async def loc_index_run(root: str = "") -> dict:
    """Run an incremental index pass over `root` (or current repo).

    Returns {new_files, skipped_files, new_symbols, stale_removed,
    errors, total_files, total_symbols, db}.

    Call this once at session start (or after a large edit) to keep the
    index fresh. Sha-deduped: unchanged files are skipped."""
    target = Path(root).expanduser().resolve() if root else _resolve_root()
    return li.do_index(target)


if __name__ == "__main__":
    mcp.run()
