#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp>=3.0",
# ]
# ///
"""kaizen drift-mcp — structural-drift detector + MCP wrapper.

Tools:
  drift_status()                — show baseline / current dirs + counts
  drift_record_baseline()       — seed baseline from current profiles
  drift_check(fail_on_drift)    — diff baseline ↔ current
  drift_explain(unit)           — detail one unit's drift

State: <repo>/.kaizen/workflow/drift-baseline/  vs  <repo>/docs/crates/
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "indexers"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "handlers"))

try:
    from fastmcp import FastMCP
    import _drift as kz_drift  # type: ignore
except ImportError as e:
    sys.stderr.write(f"kaizen-drift-mcp: missing dep: {e}\n")
    sys.exit(1)

mcp = FastMCP("kaizen-drift")

def _root() -> Path:
    env = os.environ.get("KAIZEN_DRIFT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd()

@mcp.tool()
async def drift_status() -> dict:
    """Report baseline/current dirs + profile counts. No comparison —
    just structural state."""
    root = _root()
    baseline = kz_drift.default_baseline_dir(root)
    current = kz_drift.default_current_dir(root)
    return {
        "baseline_dir": str(baseline),
        "current_dir": str(current),
        "baseline_present": baseline.is_dir(),
        "current_present": current.is_dir(),
        "baseline_count": len(kz_drift.load_profiles(baseline)),
        "current_count": len(kz_drift.load_profiles(current)),
    }

@mcp.tool()
async def drift_record_baseline() -> dict:
    """Copy every <root>/docs/crates/*.json into <root>/.kaizen/workflow/
    drift-baseline/. Creates baseline dir if absent. Run this once after
    a stable refactor checkpoint."""
    root = _root()
    try:
        return kz_drift.record_baseline(
            kz_drift.default_current_dir(root),
            kz_drift.default_baseline_dir(root),
        )
    except FileNotFoundError as e:
        return {"error": str(e)}

@mcp.tool()
async def drift_check(fail_on_drift: bool = False) -> dict:
    """Compare baseline vs current. Returns the full DriftReport as a
    dict. When `fail_on_drift=True` AND any drift detected, the dict
    includes `gate_failed=True` (callers / CI gate on this)."""
    root = _root()
    report = kz_drift.run_check(
        kz_drift.default_baseline_dir(root),
        kz_drift.default_current_dir(root),
    )
    import dataclasses
    out = {
        "baseline_dir": report.baseline_dir,
        "current_dir": report.current_dir,
        "changed": [dataclasses.asdict(u) for u in report.changed],
        "added_units": report.added_units,
        "removed_units": report.removed_units,
        "total": report.total,
        "rendered": kz_drift.format_report(report),
    }
    if fail_on_drift and report.total > 0:
        out["gate_failed"] = True
    return out

@mcp.tool()
async def drift_explain(unit: str) -> dict:
    """Detail one unit's drift. Returns the UnitDrift dict or
    {"unchanged": true} when the unit's profile is the same in both
    baseline and current."""
    root = _root()
    report = kz_drift.run_check(
        kz_drift.default_baseline_dir(root),
        kz_drift.default_current_dir(root),
        only=unit,
    )
    if unit in report.added_units:
        return {"unit": unit, "status": "added"}
    if unit in report.removed_units:
        return {"unit": unit, "status": "removed"}
    match = next((u for u in report.changed if u.unit == unit), None)
    if match is None:
        return {"unit": unit, "unchanged": True}
    import dataclasses
    return {"status": "changed", **dataclasses.asdict(match)}

if __name__ == "__main__":
    mcp.run()
