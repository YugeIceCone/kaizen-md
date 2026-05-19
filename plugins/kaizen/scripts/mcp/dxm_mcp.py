#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen dxm MCP — expose deus-ex-machina as MCP tools.

Wraps `dxm.py` so agents can query live session state, walk session
chains, replay history, and record continuity via MCP without
shelling out to bash.

## Tools

  dxm_now(session_id) — current snapshot
  dxm_tail(session_id, limit=20, back_seconds=None, agent=None)
                       — most-recent events with optional rolling window
  dxm_link(parent, child) — record parent→child continuity edge
  dxm_chain(session_id, max_depth=20) — walk ancestry back to root
  dxm_session_id(cwd=None) — autodiscover active session_id
  dxm_replay(session_id, jsonl, no_truncate=False)
                       — backfill from CC session JSONL (install-day fix)
  dxm_clean(older_than=None, all=False, dry_run=False)
                       — retention/rotation

`capture` is intentionally NOT exposed via MCP — it's a hook-only hot
path; agents writing events through MCP would create the exact lag
problem dxm solves. Use the dxm-event.sh hook for capture.

## Spawning

Mounted into the kaizen gateway via `gateway.py::SUBSERVERS`. Reachable
as `mcp__plugin_kaizen_kaizen__dxm_*(...)` once the gateway spawns.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_dxm():
    """Load dxm.py via explicit spec (mirrors the gatekeeper_mcp pattern).
    Post-DOMAIN-4: dxm.py still lives at skills/workflow/scripts/ — bridge."""
    dxm_py = SCRIPT_DIR.parents[1] / "skills" / "workflow" / "scripts" / "dxm.py"
    spec = importlib.util.spec_from_file_location(
        "kaizen_dxm_mcp_inner", dxm_py,
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load dxm.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kaizen_dxm_mcp_inner"] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    from fastmcp import FastMCP
except ImportError:
    sys.stderr.write("kaizen-dxm-mcp: fastmcp>=3.0 required\n")
    sys.exit(2)


mcp = FastMCP("kaizen-dxm")
_dxm = None


def _dxm_mod():
    """Lazy-load dxm.py once."""
    global _dxm
    if _dxm is None:
        _dxm = _load_dxm()
    return _dxm


def _ns(**kwargs):
    """Build an argparse-like namespace for dxm._cmd_* handlers."""
    class _NS:
        pass
    ns = _NS()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


# ─── now ─────────────────────────────────────────────────────────────


@mcp.tool()
async def dxm_now(session_id: str) -> dict:
    """Current-state snapshot for a session — event count, per-tool
    breakdown, last_event_at_unix, lag_seconds, parent_session_id.

    Args:
      session_id: the session whose live state to read.

    Returns:
      {session_id, event_count, by_tool, last_event_at_unix,
       lag_seconds, parent_session_id}
    """
    def _run():
        dxm = _dxm_mod()
        events = dxm._read_events(session_id)
        from collections import Counter
        import time as _t
        by_tool: Counter = Counter()
        last_ts = 0.0
        for e in events:
            tn = e.get("tool_name")
            if tn:
                by_tool[tn] += 1
            ts = e.get("ts_unix")
            if isinstance(ts, (int, float)) and ts > last_ts:
                last_ts = float(ts)
        lag = (_t.time() - last_ts) if last_ts > 0 else 0.0
        return {
            "session_id":         session_id,
            "event_count":        len(events),
            "by_tool":            dict(by_tool),
            "last_event_at_unix": last_ts if last_ts > 0 else None,
            "lag_seconds":        round(lag, 4) if last_ts > 0 else None,
            "parent_session_id":  dxm._read_parent(session_id),
        }
    return await asyncio.to_thread(_run)


# ─── tail ────────────────────────────────────────────────────────────


@mcp.tool()
async def dxm_tail(
    session_id: str,
    limit: int = 20,
    back_seconds: float | None = None,
    window_from: float | None = None,
    window_to: float | None = None,
    since_unix: float | None = None,
    agent: str | None = None,
) -> dict:
    """Most-recent events for a session.

    Args:
      session_id: required.
      limit:       max events returned (default 20, newest last).
      back_seconds: rolling window — events from (now - SECONDS) to now.
      window_from / window_to: middle slice from past (window_from > window_to).
      since_unix: absolute lower bound (alternative to back_seconds).
      agent:      filter to events with this agent_id (sub-agent scope).

    Returns:
      {session_id, events: [...], count}
    """
    def _run():
        dxm = _dxm_mod()
        import time as _t
        events = dxm._read_events(session_id)
        now = _t.time()
        lower = None
        upper = None
        if window_from is not None or window_to is not None:
            if window_from is not None: lower = now - window_from
            if window_to is not None:   upper = now - window_to
        elif back_seconds is not None:
            lower = now - back_seconds
        elif since_unix is not None:
            lower = since_unix
        if lower is not None or upper is not None:
            def _ok(e):
                ts = e.get("ts_unix")
                if not isinstance(ts, (int, float)): return False
                if lower is not None and ts <= lower: return False
                if upper is not None and ts > upper:  return False
                return True
            events = [e for e in events if _ok(e)]
        if agent:
            events = [e for e in events if e.get("agent_id") == agent]
        if limit and limit > 0:
            events = events[-limit:]
        return {"session_id": session_id, "events": events, "count": len(events)}
    return await asyncio.to_thread(_run)


# ─── link ────────────────────────────────────────────────────────────


@mcp.tool()
async def dxm_link(parent: str, child: str) -> dict:
    """Record a parent→child session-continuity edge.

    Args:
      parent: parent session_id.
      child:  child session_id (the new session continuing from parent).

    Returns:
      {parent_session_id, child_session_id, ts_unix}
    """
    def _run():
        dxm = _dxm_mod()
        import time as _t
        rec = {
            "ts_unix":           _t.time(),
            "parent_session_id": parent,
            "child_session_id":  child,
        }
        path = dxm._sessions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, separators=(",", ":")) + "\n")
        return rec
    return await asyncio.to_thread(_run)


# ─── chain ───────────────────────────────────────────────────────────


@mcp.tool()
async def dxm_chain(session_id: str, max_depth: int = 20) -> dict:
    """Walk parent_session_id from --session back to root. Cycle-safe.

    Args:
      session_id: starting session (the most recent / child).
      max_depth: bail after this many hops.

    Returns:
      {session_id, chain: [root, ..., child], depth, truncated}
    """
    def _run():
        dxm = _dxm_mod()
        links = dxm._read_all_links()
        parent_of = {}
        for r in links:
            c = r.get("child_session_id")
            p = r.get("parent_session_id")
            if c and p:
                parent_of[c] = p
        chain = [session_id]
        seen = {session_id}
        truncated = False
        current = session_id
        md = max(1, max_depth)
        for _ in range(md):
            parent = parent_of.get(current)
            if not parent:
                break
            if parent in seen:
                truncated = True
                break
            chain.append(parent)
            seen.add(parent)
            current = parent
        else:
            if parent_of.get(current):
                truncated = True
        chain.reverse()
        return {
            "session_id": session_id, "chain": chain,
            "depth": len(chain), "truncated": truncated,
        }
    return await asyncio.to_thread(_run)


# ─── session-id discovery ────────────────────────────────────────────


@mcp.tool()
async def dxm_session_id(cwd: str | None = None) -> dict:
    """Autodiscover the active session_id from cwd → ~/.claude/projects/<slug>/
    → latest-mtime *.jsonl.

    Args:
      cwd: override cwd for slug derivation (default: process cwd).

    Returns:
      {session_id | null, jsonl_path | null, cwd, slug}
    """
    def _run():
        dxm = _dxm_mod()
        cwd_path = Path(cwd or ".").resolve()
        slug = dxm._cwd_to_slug(cwd_path)
        proj = Path.home() / ".claude" / "projects" / slug
        sid = None
        jsonl_path = None
        if proj.is_dir():
            candidates = [p for p in proj.iterdir()
                           if p.is_file() and p.suffix == ".jsonl"]
            if candidates:
                jsonl_path = max(candidates, key=lambda p: p.stat().st_mtime)
                sid = jsonl_path.stem
        return {
            "session_id": sid,
            "jsonl_path": str(jsonl_path) if jsonl_path else None,
            "cwd": str(cwd_path), "slug": slug,
        }
    return await asyncio.to_thread(_run)


# ─── replay ──────────────────────────────────────────────────────────


@mcp.tool()
async def dxm_replay(session_id: str, jsonl: str,
                       no_truncate: bool = False) -> dict:
    """Backfill dxm events from a CC session JSONL — fixes install-day
    blindspot when hooks weren't registered for the active session.

    Args:
      session_id: target session for the synthesized events.
      jsonl:      path to source CC session JSONL.
      no_truncate: append to existing events file instead of truncating.

    Returns:
      {session_id, source_jsonl, events_path, synthesized_count, truncated}
    """
    def _run():
        dxm = _dxm_mod()
        args = _ns(
            session=session_id, jsonl=jsonl,
            no_truncate=no_truncate, json=False,
        )
        # _cmd_replay prints + returns rc; we re-implement the logic
        # inline to capture the data dict cleanly.
        src = Path(jsonl).expanduser()
        if not src.is_file():
            return {"error": f"jsonl not found: {src}"}
        target = dxm._events_path(session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not no_truncate and target.exists():
            target.unlink()
        synthesized = 0
        import json as _json
        with src.open("r", encoding="utf-8") as f, \
             target.open("a", encoding="utf-8") as out:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if o.get("type") != "attachment":
                    continue
                att = o.get("attachment") or {}
                if not isinstance(att, dict):
                    continue
                evt = dxm._attachment_to_event(att, session_id)
                if evt is None:
                    continue
                ts = dxm._iso_to_unix(o.get("timestamp", ""))
                if ts is None:
                    import time as _t
                    ts = _t.time()
                evt["ts_unix"] = ts
                out.write(_json.dumps(evt, separators=(",", ":"),
                                       default=str) + "\n")
                synthesized += 1
        return {
            "session_id": session_id,
            "source_jsonl": str(src.resolve()),
            "events_path": str(target.resolve()),
            "synthesized_count": synthesized,
            "truncated": not no_truncate,
        }
    return await asyncio.to_thread(_run)


# ─── clean ───────────────────────────────────────────────────────────


@mcp.tool()
async def dxm_clean(older_than: str | None = None,
                      all: bool = False,
                      dry_run: bool = False) -> dict:
    """Retention/rotation — remove stale events files by age or all.

    Args:
      older_than: NUMBER+unit, e.g. 7d, 2h, 30m, 15s. Required unless `all`.
      all:        remove EVERY file in the dxm dir.
      dry_run:    report what would be removed; mutate nothing.

    Returns:
      {dxm_dir, removed_count|would_remove_count, removed?|would_remove?}
    """
    def _run():
        dxm = _dxm_mod()
        import time as _t
        dxm_root = dxm._dxm_dir()
        if not dxm_root.is_dir():
            return {"dxm_dir": str(dxm_root), "removed_count": 0}
        candidates = []
        if all:
            candidates = [p for p in dxm_root.iterdir() if p.is_file()]
        else:
            if not older_than:
                return {"error": "older_than or all required"}
            try:
                cutoff_age = dxm._parse_age(older_than)
            except ValueError as exc:
                return {"error": str(exc)}
            cutoff_mtime = _t.time() - cutoff_age
            candidates = [
                p for p in dxm_root.iterdir()
                if p.is_file() and p.stat().st_mtime < cutoff_mtime
            ]
        if dry_run:
            return {
                "dxm_dir": str(dxm_root),
                "would_remove_count": len(candidates),
                "would_remove": sorted(str(p) for p in candidates),
                "dry_run": True,
            }
        removed = 0
        for p in candidates:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        return {
            "dxm_dir": str(dxm_root),
            "removed_count": removed,
            "removed": sorted(str(p) for p in candidates if not p.exists()),
        }
    return await asyncio.to_thread(_run)


if __name__ == "__main__":
    mcp.run()
