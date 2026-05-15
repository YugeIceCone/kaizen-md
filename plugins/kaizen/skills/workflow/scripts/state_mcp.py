#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen state-mcp — umbrella MCP server for kaizen's read-only state surface.

Consolidates the tools Claude needs to inspect runtime + per-repo state
WITHOUT requiring the user to type a slash command. One server, many tools,
no embedding-model dependency (those are in the dedicated sem-search servers).

Replaces / complements these slash commands (which stay for direct user use):

  status   → state_status()                          repo config + hook + backlog + backups
  health   → state_health(), state_health_summary()  diagnostic checks
  context  → state_context()                         CC context-window state
  cache    → state_cache_stats()                     per-repo cache count + size
  inbox    → state_inbox_peek(), state_inbox_list()  pending user messages
  observe  → state_observe_layers(), state_observe_drill(sid)
  trace    → state_trace_tail(n=20, src="", evt="")  raw event tail
            state_trace_stats()                      event counts per src

Status + health wrap their bash scripts via subprocess + return the raw
stdout as a string. The other tools wrap Python helpers directly and
return structured dicts/lists.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(f"kaizen-state-mcp: missing dep: {e}\n")
    sys.exit(1)

# Lazy imports — state_mcp shouldn't fail at startup just because
# (say) trace.py has a missing optional dep. Each tool imports its
# helper module on first call.

mcp = FastMCP("state")


from _subproc import git_repo_root as _repo_root  # noqa: E402, F401 — M2 dedup


# ─── status / health (wrap bash scripts) ─────────────────────────────


@mcp.tool()
async def state_status() -> str:
    """Repo status as the raw output of `status.sh` (config / hook /
    backlog / workflow-routing / backups / migration-candidates).

    Cheaper than the slash command (which also embeds 50+ lines of
    .md prose around the bash output). Returns text; parse if needed."""
    sh = SCRIPT_DIR / "status.sh"
    r = subprocess.run(
        ["bash", str(sh)],
        cwd=_repo_root(), capture_output=True, text=True,
    )
    return r.stdout or r.stderr or "(no status output)"


@mcp.tool()
async def state_health() -> dict:
    """Diagnostic health-check (wraps `health.sh`). Returns
    {ok: bool, exit_code: int, output: str} — `ok` is True iff
    exit_code == 0 (no RED findings)."""
    sh = SCRIPT_DIR / "health.sh"
    r = subprocess.run(
        ["bash", str(sh)],
        cwd=_repo_root(), capture_output=True, text=True,
    )
    return {
        "ok": r.returncode == 0,
        "exit_code": r.returncode,
        "output": r.stdout,
    }


@mcp.tool()
async def state_health_summary() -> dict:
    """Compact health summary: counts of ✓ / ∘ / ✗ across all
    sections. Cheaper than state_health() when you only need a
    boolean + counts, not the full report."""
    full = await state_health()
    lines = full["output"].splitlines()
    return {
        "ok": full["ok"],
        "exit_code": full["exit_code"],
        "green": sum(1 for ln in lines if "✓" in ln),
        "warn": sum(1 for ln in lines if ("∘" in ln) or ("!" in ln)),
        "fail": sum(1 for ln in lines if "✗" in ln),
        "result_line": next((ln for ln in lines if ln.startswith("Result:")), ""),
    }


# ─── context ────────────────────────────────────────────────────────


@mcp.tool()
async def state_context() -> dict:
    """Claude Code's current context-window state.

    Returns {tokens, limit, pct, zone, recommendation}.
    Zone is one of green/yellow/red based on pct of limit.
    Returns {tokens: None, ...} if the CLAUDE_CONTEXT_TOKENS env
    var isn't set and no stdin JSON is provided."""
    import context as ctx  # type: ignore
    tokens = ctx.get_tokens("")
    limit = ctx.get_limit()
    pct = (tokens * 100 / limit) if (tokens is not None and limit > 0) else None
    zone = "unknown"
    rec = "no context-window data available"
    if pct is not None:
        if pct < 70:
            zone, rec = "green", "ok"
        elif pct < 90:
            zone, rec = "yellow", "consider /compact soon"
        else:
            zone, rec = "red", "/compact now"
    return {
        "tokens": tokens,
        "limit": limit,
        "pct": round(pct, 1) if pct is not None else None,
        "zone": zone,
        "recommendation": rec,
    }


# ─── cache ──────────────────────────────────────────────────────────


@mcp.tool()
async def state_cache_stats() -> dict:
    """Per-repo cache state — {count, bytes, dir, exists}.

    The cache lives at <repo>/.kaizen/cache/ and stores hash-keyed
    JSON entries (compile-barrier verdicts, agent diff caches, etc).
    Empty == fresh repo or just-cleared cache."""
    import cache as ch  # type: ignore
    return ch.stats()


# ─── inbox ──────────────────────────────────────────────────────────


@mcp.tool()
async def state_inbox_peek(n: int = 5) -> list[dict]:
    """Read pending inbox messages WITHOUT marking them drained.

    Returns up to N pending {ts, sid, text, drained, ...}. Use this
    to see what the user typed during a busy tool sequence. Drain
    via the slash command (`/kaizen:inbox drain`) — that's mutating
    and stays user-driven."""
    import inbox as ix  # type: ignore
    msgs = ix.list_messages(pending_only=True)
    return msgs[:n]


@mcp.tool()
async def state_inbox_list(pending_only: bool = True) -> list[dict]:
    """All inbox messages (defaults to pending-only).

    Returns the full list as dicts. Use for "what has the user
    queued?" surveys; use state_inbox_peek for the next few."""
    import inbox as ix  # type: ignore
    return ix.list_messages(pending_only=pending_only)


# ─── observe ────────────────────────────────────────────────────────


@mcp.tool()
async def state_observe_layers() -> dict:
    """All 6 observability layers in one snapshot.

    Returns {L1_*, L2_*, L3_*, L4_*, L5_*, L6_*} dicts — stderr
    captures, CC transcript, kaizen trace, domain logs, per-repo
    state, plugin global. Use as the entry point for any cross-
    layer drill-down."""
    import observe as ob  # type: ignore
    return ob.cmd_layers()


@mcp.tool()
async def state_observe_drill(sid: str) -> str:
    """Cross-layer drill for one session id — returns the markdown
    drill report (same shape as `kaizen-observe drill <sid>`).

    Pass an `sid` from state_observe_layers() or kaizen-trace search."""
    import observe as ob  # type: ignore
    return ob.cmd_drill(sid)


# ─── trace (raw event tail) ─────────────────────────────────────────


@mcp.tool()
async def state_trace_tail(n: int = 20, src: str = "", evt: str = "") -> list[dict]:
    """Most recent N kaizen trace events (raw, no sem search).

    `src` filters by source (e.g. "hook", "agent", "llm"). `evt`
    filters by event name. Empty = no filter. Returns list of
    event dicts.

    For semantic search across the same event log, use the
    `kaizen-trace-search` MCP server tools instead."""
    import trace as tr  # type: ignore
    return tr.do_tail(n=n, src=src, evt=evt)


@mcp.tool()
async def state_trace_stats() -> dict:
    """Quick event-log stats — {total, by_src, by_evt} counts.

    Reads the JSONL log directly; no sem index required."""
    import trace as tr  # type: ignore
    from collections import Counter
    events = tr.do_tail(n=10_000)  # cap to 10k for speed
    by_src = Counter(e.get("src", "") for e in events)
    by_evt = Counter(e.get("evt", "") for e in events)
    return {
        "total_sampled": len(events),
        "by_src": dict(by_src.most_common(10)),
        "by_evt": dict(by_evt.most_common(10)),
    }


if __name__ == "__main__":
    mcp.run()
