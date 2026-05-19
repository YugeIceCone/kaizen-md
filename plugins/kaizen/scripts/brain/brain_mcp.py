#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "PyYAML>=6.0",
# ]
# ///
"""kaizen-brain-mcp — MCP server exposing the Second Brain.

FastMCP + async wrappers around brain.py / build_index.py /
brain_promote.py / brain_audit.py / brain_evolve.py. Every capture
/ search / promotion / audit / evolution capability the CLI exposes
is reachable as an MCP tool.

Tools:

  brain_capture(text, type_hint=None, confidence=None, tier_hint=None,
                subject=None)
    Capture a thought via the schema-driven flow. Returns the report
    (type, tier, action=created|merged, path, journal, sources_count).

  brain_detect(text)
    Classify text without writing.

  brain_status()
    File counts per brain subdir + persona presence.

  brain_path()
    Resolved brain root + project-memory root + domain dir.

  brain_search(query, top_k=10, type=None, subdir=None, min_confidence=None)
    SQLite-indexed search over the brain. Semantic when embedder
    available; LIKE fallback otherwise. Filters by type / subdir /
    min_confidence.

  brain_index_build()
    Rebuild the brain index.

  brain_index_stats()
    Counts per type / subdir / freshness.

  brain_get(item_id)
    Fetch one indexed note by id.

  brain_promote_preview(source=None, filter=None)
    List project-memory entries eligible for brain promotion.

  brain_promote_apply(source=None, filter=None)
    Promote eligible entries (copy to brain, tombstone source).

  brain_audit(apply=False, limit_commits=10, limit_inbox=20)
    End-of-session discovery audit. apply=True writes drafts to Inbox.

  brain_evolve(stale_days=30)
    Consolidation + freshness report (no auto-writes).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — build_index at scripts/indexers/; kaizen helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))

try:
    from fastmcp import FastMCP
    import _brain  # type: ignore
    import brain as _brain_cli  # type: ignore
    import build_index as bi  # type: ignore
    import brain_promote as bp  # type: ignore
    import brain_audit as ba  # type: ignore
    import brain_evolve as be  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-brain-mcp: missing dep: {e}\n"
        "Run: pip install mcp PyYAML (or rely on the uv shebang)\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-brain")


# ─── Capture / detect / status / path ────────────────────────────────


@mcp.tool()
async def brain_capture(
    text: str,
    type_hint: Optional[str] = None,
    confidence: Optional[float] = None,
    tier_hint: Optional[str] = None,
    subject: Optional[str] = None,
) -> dict:
    """Capture a thought into the brain. Schema-driven type detection
    + routing. Returns the report dict."""
    return await _brain_cli.capture_async(
        text=text,
        type_hint=type_hint,
        confidence=confidence,
        tier_hint=tier_hint,
        subject=subject,
    )


@mcp.tool()
async def brain_detect(text: str) -> dict:
    """Detect the epistemic type of a string without writing.
    Returns {"type": "world-fact" | "belief" | "observation" | "experience"}.
    """
    return {"type": _brain.detect_type(text)}


@mcp.tool()
async def brain_status() -> dict:
    """Brain file counts per subdir + persona presence."""
    return _brain_cli.status()


@mcp.tool()
async def brain_path() -> dict:
    """Resolved brain + project-memory + domain paths."""
    return {
        "brain_root": str(_brain.brain_root()),
        "project_memory_root": str(_brain.project_memory_root()),
        "domain_dir": str(_brain._DOMAIN_DIR),
        "index_db": str(bi.db_path()),
    }


# ─── Index / search / get ────────────────────────────────────────────


@mcp.tool()
async def brain_search(
    query: str,
    top_k: int = 10,
    type: Optional[str] = None,
    subdir: Optional[str] = None,
    min_confidence: Optional[float] = None,
) -> list:
    """Search the brain index. Returns top_k matching notes with
    typed metadata. Filters apply to BOTH semantic and LIKE paths."""
    return await asyncio.to_thread(
        bi.do_search,
        query,
        top_k=top_k,
        type_filter=type,
        subdir_filter=subdir,
        min_confidence=min_confidence,
    )


@mcp.tool()
async def brain_index_build() -> dict:
    """(Re)build the brain index. Walks Notes/ + Projects/ + People/
    + Areas/; embeds + upserts; cleans stale rows."""
    return await asyncio.to_thread(bi.do_index)


@mcp.tool()
async def brain_index_stats() -> dict:
    """Per-type / per-subdir / per-freshness row counts."""
    return await asyncio.to_thread(bi.do_stats)


@mcp.tool()
async def brain_get(item_id: int) -> dict:
    """Fetch one note by SQLite id."""
    out = await asyncio.to_thread(bi.do_get, item_id)
    return out or {"error": f"id {item_id} not found"}


# ─── Promote / audit / evolve ────────────────────────────────────────


@mcp.tool()
async def brain_promote_preview(
    source: Optional[str] = None,
    filter: Optional[str] = None,
) -> dict:
    """List project-memory entries eligible for brain promotion.

    source: restrict to one project slug (e.g. -home-x-workspace-shodan)
    filter: filename glob (e.g. 'feedback_*.md')
    """
    return await asyncio.to_thread(
        bp.promote,
        project_slug=source,
        filter_glob=filter,
        apply=False,
    )


@mcp.tool()
async def brain_promote_apply(
    source: Optional[str] = None,
    filter: Optional[str] = None,
) -> dict:
    """Promote eligible project-memory entries. Copies to brain;
    tombstones source files. Returns the apply report."""
    return await asyncio.to_thread(
        bp.promote,
        project_slug=source,
        filter_glob=filter,
        apply=True,
    )


@mcp.tool()
async def brain_audit(
    apply: bool = False,
    limit_commits: int = 10,
    limit_inbox: int = 20,
) -> dict:
    """End-of-session discovery audit. Scans inbox + commits + drafts
    + loop state for non-obvious learnings. apply=True writes
    candidates as drafts to brain/Inbox/."""
    return await asyncio.to_thread(
        ba.audit,
        apply=apply,
        limit_commits=limit_commits,
        limit_inbox=limit_inbox,
    )


@mcp.tool()
async def brain_evolve(stale_days: int = 30) -> dict:
    """Consolidation + freshness report (read-only).
    Reports duplicates, freshness drift, and Persona.md vs Notes drift."""
    return await asyncio.to_thread(be.evolve, stale_days=stale_days)


if __name__ == "__main__":
    mcp.run()
