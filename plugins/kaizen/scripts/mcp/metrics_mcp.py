#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen-metrics-mcp — MCP server exposing the metrics surface.

Tools:

  metrics_session(sid=None)       per-session rollup
  metrics_lifetime(since=None)    all-time or windowed rollup
  metrics_never_used(kind)        what's available but never invoked
  metrics_top(kind, n=10)         most-used artifacts of a kind
  metrics_skips(sid=None)         skill-skip candidates for a session
  metrics_path()                  resolved trace log path

Agents call these to self-audit. Pair with `brain_audit` for end-
of-session reflection: brain_audit surfaces user-quote candidates,
metrics_skips surfaces structural-discipline gaps.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — relocated modules + legacy helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "handlers"))

try:
    from fastmcp import FastMCP
    import metrics  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-metrics-mcp: missing dep: {e}\n"
        "Run: pip install mcp (or rely on the uv shebang)\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-metrics")


@mcp.tool()
async def metrics_session(sid: Optional[str] = None) -> dict:
    """Per-session rollup. Default sid is the latest active session.
    Returns event counts by tool/skill/mcp/evt + earliest/latest ts."""
    sid = sid or await asyncio.to_thread(metrics.latest_session_id)
    if not sid:
        return {"error": "no sessions found in trace"}
    r = await asyncio.to_thread(metrics.rollup_events, sid=sid)
    out = r.to_dict()
    out["sid"] = sid
    return out


@mcp.tool()
async def metrics_lifetime(since: Optional[str] = None) -> dict:
    """All-time rollup (or --since DUR — accepts '7d', '30m', ISO).
    Returns the same shape as metrics_session minus the sid field."""
    cutoff = metrics.parse_duration(since) if since else None
    r = await asyncio.to_thread(metrics.rollup_events, since=cutoff)
    return r.to_dict()


@mcp.tool()
async def metrics_never_used(kind: str = "skill") -> dict:
    """Features available but never invoked in the trace.

    kind: 'skill' | 'tool' | 'mcp' | 'bin'
    """
    return await asyncio.to_thread(metrics.never_used, kind)


@mcp.tool()
async def metrics_top(kind: str = "skill", n: int = 10) -> list:
    """Most-used artifacts of a kind. Returns [{name, count}, ...]
    sorted descending by count.

    kind: 'skill' | 'tool' | 'mcp' | 'evt'
    """
    items = await asyncio.to_thread(metrics.top_n, kind, n)
    return [{"name": name, "count": count} for name, count in items]


@mcp.tool()
async def metrics_skips(sid: Optional[str] = None) -> dict:
    """Detect skill-skips for a session — touched files that should
    have triggered a skill load, but the skill was never loaded.
    Returns {sid, skips: [{skill, rationale, touched_files,
    touched_count}, ...]}."""
    skips = await asyncio.to_thread(metrics.detect_skips, sid)
    return {
        "sid": sid or await asyncio.to_thread(metrics.latest_session_id),
        "skips": skips,
    }


@mcp.tool()
async def metrics_path() -> dict:
    """Print the resolved trace log path."""
    return {"trace_log": str(metrics.trace_log_path())}


@mcp.tool()
async def metrics_graveyard(kind: str = "skill", stale_days: int = 14) -> dict:
    """Cold-artifact candidates — never-used AND the trace has been
    *watching* this kind for >= stale_days. Returns ready=False with
    a caveat when the trace is too young to judge (guards against
    false-dead flagging on a young trace). Does NOT archive anything.

    kind: 'skill' | 'mcp' | 'bin' | 'tool'
    """
    return await asyncio.to_thread(metrics.graveyard, kind, stale_days)


@mcp.tool()
async def metrics_smoke_mcp() -> dict:
    """Smoke-test every MCP server — import each *_mcp.py module,
    verify a module-level FastMCP instance exists. Returns
    {checked, passed, failed: [{name, error}], skipped}. A server
    that sys.exit()s on a missing opt-in dep counts as a failure,
    not a crash."""
    return await asyncio.to_thread(metrics.smoke_mcp)


@mcp.tool()
async def metrics_noise() -> dict:
    """Hook/tool noise dashboard — aggregates 3 dynamic-trace axes
    (hook_cascade + silent_fail + turn_density) into one verdict.

    Returns {verdict, counts: {<axis>.<metric>: int, ...}, axes:
    {<axis>: <axis_envelope>}}. Verdict rolls up: any axis red → red;
    any yellow → yellow; else green.

    Use to surface what's misbehaving at runtime — separate from
    static wiring axes (hook-coverage / mcp-coverage / *-trace-coverage)
    which are coverage, not noise."""
    import subprocess, json as _json
    quality = Path(__file__).resolve().parents[1] / "quality"
    axes = {
        "hook_cascade":  "hook_cascade.py",
        "silent_fail":   "silent_fail.py",
        "turn_density":  "turn_density.py",
    }

    def _run_one(script: str) -> dict:
        r = subprocess.run(
            ["python3", str(quality / script), "gaps", "--json"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return {"error": (r.stderr or r.stdout or "").strip(),
                    "verdict": "red", "counts": {}, "data": {}}
        try:
            return _json.loads(r.stdout)
        except _json.JSONDecodeError as e:
            return {"error": f"non-JSON output: {e}", "verdict": "red",
                    "counts": {}, "data": {}}

    results = await asyncio.gather(*[
        asyncio.to_thread(_run_one, script)
        for script in axes.values()
    ])
    axes_envs = dict(zip(axes.keys(), results))
    verdicts = [e.get("verdict", "green") for e in results]
    verdict = ("red" if "red" in verdicts
               else "yellow" if "yellow" in verdicts
               else "green")
    counts: dict[str, int] = {}
    for axis_id, env in axes_envs.items():
        for k, v in env.get("counts", {}).items():
            counts[f"{axis_id}.{k}"] = v
    return {"verdict": verdict, "counts": counts, "axes": axes_envs}


if __name__ == "__main__":
    mcp.run()
