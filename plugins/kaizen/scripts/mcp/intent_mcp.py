#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
#     "pyyaml>=6.0",
# ]
# ///
"""kaizen intent MCP — expose kaizen-intent as MCP tools.

Lets agents query the intent registry, match text/events to registered
intents, get top-confidence suggestions, and scan a session's recent
dxm events for event_pattern hits — all via MCP, no subprocess.

## Tools

  intent_list() — list all registered intents
  intent_match(text=None, events=None) — return matching intents
  intent_suggest(text=None, events=None) — return top match
  intent_scan(session_id, back_seconds=60.0) — pull dxm events + match

## Spawning

Mounted into the kaizen gateway via `gateway.py::SUBSERVERS`. Reachable
as `mcp__plugin_kaizen_kaizen__intent_*(...)` once the gateway spawns.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

def _load_intent():
    spec = importlib.util.spec_from_file_location(
        "kaizen_intent_mcp_inner", SCRIPT_DIR.parent / "intent" / "intent.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("could not load intent.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kaizen_intent_mcp_inner"] = mod
    spec.loader.exec_module(mod)
    return mod

try:
    from fastmcp import FastMCP
except ImportError:
    sys.stderr.write("kaizen-intent-mcp: fastmcp>=3.0 required\n")
    sys.exit(2)

mcp = FastMCP("kaizen-intent")
_intent = None

def _intent_mod():
    global _intent
    if _intent is None:
        _intent = _load_intent()
    return _intent

# ─── list ────────────────────────────────────────────────────────────

@mcp.tool()
async def intent_list() -> dict:
    """List all registered intents.

    Returns:
      {intents: [{id, description, trigger_kinds, confidence}, ...], count}
    """
    def _run():
        intent = _intent_mod()
        try:
            intents = intent._load_intents()
        except (FileNotFoundError, RuntimeError) as exc:
            return {"error": str(exc), "intents": [], "count": 0}
        summary = [
            {
                "id":            i.get("id"),
                "description":   i.get("description", ""),
                "trigger_kinds": sorted({
                    t.get("kind", "phrase") for t in (i.get("triggers") or [])
                }),
                "confidence":    intent._intent_confidence(i),
            }
            for i in intents
        ]
        return {"intents": summary, "count": len(summary)}
    return await asyncio.to_thread(_run)

# ─── match ───────────────────────────────────────────────────────────

@mcp.tool()
async def intent_match(text: str | None = None,
                         events: list[dict] | None = None) -> dict:
    """Return all intents matching the supplied text and/or events.
    Sorted by confidence DESC.

    Args:
      text:   text to match phrase triggers against (e.g. user prompt)
      events: list of dxm event dicts to match event_pattern triggers

    Returns:
      {matched: [{id, description, confidence, action}, ...], count}
    """
    def _run():
        intent = _intent_mod()
        try:
            intents = intent._load_intents()
        except (FileNotFoundError, RuntimeError) as exc:
            return {"error": str(exc), "matched": [], "count": 0}
        t = text or ""
        ev = events or []
        matched = []
        for i in intents:
            if intent._intent_matches(i, t, ev):
                matched.append({
                    "id":          i.get("id"),
                    "description": i.get("description", ""),
                    "confidence":  intent._intent_confidence(i),
                    "action":      i.get("action") or {},
                })
        matched.sort(key=lambda m: -m["confidence"])
        return {"matched": matched, "count": len(matched)}
    return await asyncio.to_thread(_run)

# ─── suggest ─────────────────────────────────────────────────────────

@mcp.tool()
async def intent_suggest(text: str | None = None,
                           events: list[dict] | None = None) -> dict:
    """Return the highest-confidence matching intent, or null when none.

    Args:
      text:   text to match phrase triggers
      events: list of dxm events to match event_pattern triggers

    Returns:
      {intent: {id, description, confidence, action} | null}
    """
    def _run():
        intent = _intent_mod()
        try:
            intents = intent._load_intents()
        except (FileNotFoundError, RuntimeError) as exc:
            return {"error": str(exc), "intent": None}
        t = text or ""
        ev = events or []
        best = None
        for i in intents:
            if intent._intent_matches(i, t, ev):
                if best is None or intent._intent_confidence(i) > intent._intent_confidence(best):
                    best = i
        if best is None:
            return {"intent": None}
        return {"intent": {
            "id":          best.get("id"),
            "description": best.get("description", ""),
            "confidence":  intent._intent_confidence(best),
            "action":      best.get("action") or {},
        }}
    return await asyncio.to_thread(_run)

# ─── scan ────────────────────────────────────────────────────────────

@mcp.tool()
async def intent_scan(session_id: str, back_seconds: float = 60.0) -> dict:
    """Pull last N seconds of dxm events for a session + run match.
    Convenience composition: dxm_tail + intent_match.

    Args:
      session_id: target session whose dxm events to read
      back_seconds: rolling window (default 60)

    Returns:
      {session_id, back_seconds, event_count, matched: [...], count}
    """
    def _run():
        intent = _intent_mod()
        try:
            intents = intent._load_intents()
        except (FileNotFoundError, RuntimeError) as exc:
            return {"error": str(exc), "matched": [], "count": 0}

        # Read dxm events directly (no subprocess)
        env = os.environ.get("KAIZEN_DXM_DIR")
        if env:
            dxm_root = Path(os.path.expandvars(env)).expanduser()
        else:
            dxm_root = Path.home() / ".claude" / ".kaizen" / "dxm"
        events_path = dxm_root / f"events-{session_id}.jsonl"

        events = []
        if events_path.is_file():
            cutoff = time.time() - back_seconds
            try:
                with events_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            e = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = e.get("ts_unix")
                        if isinstance(ts, (int, float)) and ts >= cutoff:
                            events.append(e)
            except OSError:
                pass

        matched = []
        for i in intents:
            if intent._intent_matches(i, "", events):
                matched.append({
                    "id":          i.get("id"),
                    "description": i.get("description", ""),
                    "confidence":  intent._intent_confidence(i),
                    "action":      i.get("action") or {},
                })
        matched.sort(key=lambda m: -m["confidence"])
        return {
            "session_id":  session_id,
            "back_seconds": back_seconds,
            "event_count": len(events),
            "matched":     matched,
            "count":       len(matched),
        }
    return await asyncio.to_thread(_run)

if __name__ == "__main__":
    mcp.run()
