"""kaizen-blueprint state — tiny in-memory-as-disk cache for plan metadata.

Holds a few KB of summary per recently-opened plan so common ops
(list / scan / pick-an-index) don't re-parse the full blueprint JSON
every call. The cache is INDEX-ONLY (id / kind / status / title per
item) — never holds full content. Full-item reads still hit the source
file (the cache stays cheap + tamper-evident).

Stored at `.kaizen/cache/blueprint-state.json`:

    {
      "active": "/abs/path/to/plan.json",
      "plans": {
        "/abs/path/to/plan.json": {
          "mtime": 1716240000.0,
          "size_bytes": 29773,
          "project": "kaizen-md",
          "summary": "...",
          "n_items": 23,
          "items": [
            {"index": 0, "id": "01", "kind": "plan", "status": "draft",
             "title": "Unify artifact generation..."},
            ...
          ],
          "status_rollup": {"draft": 5, "active": 14, "shipped": 4},
          "kind_rollup": {"plan": 1, "decision": 5, ...},
          "cached_at": "2026-05-20T20:30:00Z"
        }
      }
    }

Staleness rule: cache entry is stale if source mtime > cache mtime
OR size_bytes differs. Stale entries auto-refresh on next access.

Stdlib + _atomic for writes. Pure functions otherwise.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent / "io"))
import _atomic  # noqa: E402


def _cache_path() -> Path:
    """Locate the cache file. Honors KAIZEN_BLUEPRINT_STATE env override
    for test sandboxing; otherwise <repo>/.kaizen/cache/blueprint-state.json."""
    override = os.environ.get("KAIZEN_BLUEPRINT_STATE")
    if override:
        return Path(override)
    # Walk up to find the .kaizen dir (works from any cwd inside a repo).
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        kz = cur / ".kaizen"
        if kz.is_dir():
            return kz / "cache" / "blueprint-state.json"
        cur = cur.parent
    # Fallback: $HOME/.cache/kaizen-blueprint-state.json
    return Path.home() / ".cache" / "kaizen-blueprint-state.json"


def _read_cache() -> dict:
    p = _cache_path()
    if not p.is_file():
        return {"active": None, "plans": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active": None, "plans": {}}


def _write_cache(state: dict) -> None:
    _atomic.atomic_write_json(_cache_path(), state, sort_keys=False)


def _stat(path: Path) -> tuple[float, int]:
    """(mtime, size) for the source plan file."""
    st = path.stat()
    return st.st_mtime, st.st_size


def _summarize_plan(plan_path: Path) -> dict:
    """Compute the cache row for one plan. Reads + parses once."""
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    status_rollup: dict[str, int] = {}
    kind_rollup: dict[str, int] = {}
    items_idx: list[dict] = []
    for i, it in enumerate(items):
        kind = it.get("kind", "")
        status = it.get("status", "")
        kind_rollup[kind] = kind_rollup.get(kind, 0) + 1
        status_rollup[status] = status_rollup.get(status, 0) + 1
        items_idx.append({
            "index": i,
            "id": it.get("id", ""),
            "kind": kind,
            "status": status,
            "title": it.get("title", "")[:80],
        })
    mtime, size = _stat(plan_path)
    return {
        "mtime": mtime,
        "size_bytes": size,
        "project": data.get("project", ""),
        "summary": (data.get("summary") or "")[:200],
        "n_items": len(items),
        "items": items_idx,
        "status_rollup": status_rollup,
        "kind_rollup": kind_rollup,
        "cached_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ─── Public API ─────────────────────────────────────────────────────────

def touch(plan_path: str | Path) -> dict:
    """Refresh the cache entry for `plan_path` and mark it active.
    Returns the entry. Called automatically on every CLI read."""
    p = Path(plan_path).resolve()
    state = _read_cache()
    entry = state["plans"].get(str(p))
    if entry:
        mtime, size = _stat(p)
        if mtime == entry["mtime"] and size == entry["size_bytes"]:
            state["active"] = str(p)
            _write_cache(state)
            return entry
    # Stale or absent — rebuild
    entry = _summarize_plan(p)
    state["plans"][str(p)] = entry
    state["active"] = str(p)
    _write_cache(state)
    return entry


def get_active() -> dict | None:
    """Return the active plan's cache entry, or None if no active plan."""
    state = _read_cache()
    active = state.get("active")
    if not active:
        return None
    return state["plans"].get(active)


def get_entry(plan_path: str | Path) -> dict | None:
    """Return the cache entry for `plan_path` without touching active."""
    p = str(Path(plan_path).resolve())
    return _read_cache()["plans"].get(p)


def list_cached() -> list[dict]:
    """Return all cached plan rows: path + project + n_items + active flag."""
    state = _read_cache()
    active = state.get("active")
    rows: list[dict] = []
    for path, entry in sorted(state.get("plans", {}).items()):
        rows.append({
            "path": path,
            "active": path == active,
            "project": entry.get("project", ""),
            "n_items": entry.get("n_items", 0),
            "cached_at": entry.get("cached_at", ""),
            "size_kb": round((entry.get("size_bytes") or 0) / 1024, 1),
        })
    return rows


def clear(plan_path: str | Path | None = None) -> None:
    """Drop one plan from the cache, or clear all if path=None."""
    state = _read_cache()
    if plan_path is None:
        state = {"active": None, "plans": {}}
    else:
        p = str(Path(plan_path).resolve())
        state["plans"].pop(p, None)
        if state.get("active") == p:
            state["active"] = None
    _write_cache(state)


def set_active(plan_path: str | Path) -> None:
    """Set the active plan without rebuilding its cache entry. Useful
    when switching between known plans."""
    p = str(Path(plan_path).resolve())
    state = _read_cache()
    if p not in state["plans"]:
        # Auto-touch if not yet cached
        touch(p)
        return
    state["active"] = p
    _write_cache(state)


def quick_scan() -> dict | None:
    """1-roundtrip metadata pull for the active plan. Returns the
    items[] index + rollups WITHOUT reading the source file.

    Use this from an agent to decide which item to fetch next; pull
    the full item via blueprint.show <file> <N> only after picking.
    """
    return get_active()


__all__ = [
    "touch", "get_active", "get_entry", "list_cached",
    "clear", "set_active", "quick_scan",
]
