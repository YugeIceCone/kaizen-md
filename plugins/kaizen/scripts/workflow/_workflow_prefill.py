"""Emit an annotation block for the SessionStart intake hook when the
project has persisted workflow defaults at .kaizen/workflow.json.

Consumed by hooks/claude/session-intake.sh — concatenated into the
AskUserQuestion instructional body so the user sees their saved picks
as defaults to confirm-or-override (Phase 6 of /kaizen:workflow
full-automation).

Usage:
    python3 _workflow_prefill.py --from <path-to-workflow.json>

Output: prose annotation (empty if file missing or has no usable
fields). Never errors on malformed JSON — best-effort.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

def build_prefill(cfg: dict) -> str:
    """Build the annotation text from a parsed workflow.json dict."""
    if not cfg:
        return ""

    lines: list[str] = []
    run_mode = cfg.get("run_mode")
    schema_name = cfg.get("schema_name")
    routine = cfg.get("routine")
    disciplines = cfg.get("disciplines") or []
    threshold = cfg.get("auto_handoff_threshold")

    # If nothing useful, emit empty
    if not any([run_mode, disciplines, threshold is not None]):
        return ""

    lines.append("")
    lines.append("─── PERSISTED workflow defaults (from .kaizen/workflow.json) ───")
    lines.append("")
    lines.append("These were saved previously via `kaizen-workflow-config set`.")
    lines.append("Pre-fill the AskUserQuestion picks from these unless the user")
    lines.append("explicitly redirects:")
    lines.append("")
    if run_mode:
        if run_mode == "schema" and schema_name:
            lines.append(f"  Q1 mode:         schema → {schema_name}")
        elif run_mode == "routine" and routine:
            lines.append(f"  Q1 mode:         routine → {routine}")
        else:
            lines.append(f"  Q1 mode:         {run_mode}")
    if disciplines:
        lines.append(f"  Q2/Q3 bundles:   {', '.join(disciplines)}")
    if threshold is not None:
        if threshold == "disabled":
            lines.append("  Q4 threshold:    Disabled")
        else:
            lines.append(f"  Q4 threshold:    {threshold}%")
    lines.append("")

    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="src", required=True, type=Path,
                   help="Path to workflow.json")
    args = p.parse_args(argv)

    if not args.src.exists():
        return 0  # empty output = no prefill (file missing → first run)
    try:
        cfg = json.loads(args.src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0  # best-effort: corrupt file = no prefill (don't break intake)

    out = build_prefill(cfg)
    if out:
        print(out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
