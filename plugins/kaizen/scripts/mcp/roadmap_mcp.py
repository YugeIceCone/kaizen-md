#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen roadmap-mcp — programmatic phase-progress for an active plan.

Wraps `roadmap_status.py` so Claude can query "how far am I through
this phased work" without parsing the handoff manually.

## Tools

  roadmap_progress()           dashboard + per-phase counts
  roadmap_next()               next pending item ({id, title, ...} or null)
  roadmap_phases()             phase summaries (number, title, done, total)
  roadmap_phase(number)        full item list for one phase
  roadmap_path()               resolved handoff file path

## State

Reads the newest `plans/*handoff*.md` in the spawning project's cwd.
Override with KAIZEN_ROADMAP_HANDOFF env var.

## Spawning

Registered in .mcp.json as `roadmap`. CC spawns on first
`mcp__plugin_kaizen_roadmap__*` invocation.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
# MIGRATION BRIDGE — relocated modules + legacy helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "handlers"))

try:
    from fastmcp import FastMCP
    import roadmap_status as rs  # type: ignore
except ImportError as e:
    sys.stderr.write(
        f"kaizen-roadmap-mcp: missing dep: {e}\n"
        "Ensure mcp>=1.0 is installed.\n"
    )
    sys.exit(1)


mcp = FastMCP("kaizen-roadmap")


def _load() -> tuple[list[rs.Phase], Path | None]:
    return rs._load_phases()


@mcp.tool()
async def roadmap_progress() -> dict:
    """Phase-progress dashboard (machine-readable).

    Returns {handoff, phases: [{number, title, done, total, pct, items}],
    next, dashboard_text}. `dashboard_text` is the same compact bar-
    chart format `kaizen-roadmap progress` prints — useful for one-shot
    surfacing in chat without rebuilding from `phases`."""
    phases, path = _load()
    if path is None:
        return {"present": False, "error": "no handoff file found"}
    nxt = rs.find_next_pending(phases)
    return {
        "present": True,
        "handoff": str(path),
        "phases": [
            {
                "number": p.number,
                "title": p.title,
                "done": p.done,
                "total": p.total,
                "pct": round(p.pct, 1),
                "items": [dataclasses.asdict(it) for it in p.items],
            }
            for p in phases
        ],
        "next": dataclasses.asdict(nxt) if nxt else None,
        "dashboard_text": rs.render_dashboard(phases),
    }


@mcp.tool()
async def roadmap_next() -> dict:
    """Just the next pending item. Returns the Item dict, or
    {"empty": true} when all phases are complete."""
    phases, path = _load()
    if path is None:
        return {"error": "no handoff file found"}
    nxt = rs.find_next_pending(phases)
    if nxt is None:
        return {"empty": True}
    return dataclasses.asdict(nxt)


@mcp.tool()
async def roadmap_phases() -> list[dict]:
    """Compact list of phase summaries (no per-item detail). Use
    roadmap_phase(N) for the full items of one phase."""
    phases, path = _load()
    if path is None:
        return []
    return [
        {"number": p.number, "title": p.title,
         "done": p.done, "total": p.total, "pct": round(p.pct, 1)}
        for p in phases
    ]


@mcp.tool()
async def roadmap_phase(number: int) -> dict:
    """Full item list for one phase. Returns {number, title, items: [...]}
    or {"error": "..."} when the phase doesn't exist."""
    phases, path = _load()
    if path is None:
        return {"error": "no handoff file found"}
    target = next((p for p in phases if p.number == number), None)
    if target is None:
        return {"error": f"no Phase {number} in handoff"}
    return {
        "number": target.number,
        "title": target.title,
        "done": target.done,
        "total": target.total,
        "pct": round(target.pct, 1),
        "items": [dataclasses.asdict(it) for it in target.items],
    }


@mcp.tool()
async def roadmap_path() -> dict:
    """Resolved handoff file path. {present, path} — useful for the
    agent to know which file to edit when marking items done."""
    p = rs.resolve_handoff_path()
    return {"present": p is not None, "path": str(p) if p else None}


if __name__ == "__main__":
    mcp.run()
