#!/usr/bin/env python3
"""Plan loader — resolves Mode A (inline chunks) and Mode B (chunks: glob) to a uniform in-memory dict.

After load_plan(path), plan["chunks"] is always a list[dict] and plan["merge"] is always a dict — regardless of how the YAML was authored. Downstream (validator, dispatcher, render) is mode-agnostic.

See .kaizen/superpowers/templates/parallel-branches/ON_DISK_LAYOUT.md for Mode A vs Mode B.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("parallel-branches: PyYAML required\n")
    raise


def load_plan(plan_path: Path) -> dict:
    """Load + normalize a master plan.

    Mode A (chunks: [...]) returns plan unchanged.
    Mode B (chunks: "./glob/*.yaml") resolves the glob, loads each file, replaces.
    Same for merge: inline dict OR path-to-file.
    """
    plan_path = Path(plan_path)
    base = plan_path.parent
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

    chunks_val = plan.get("chunks")
    if isinstance(chunks_val, str):
        # Mode B — glob relative to plan.yaml
        glob = chunks_val.removeprefix("./")
        files = sorted(base.glob(glob))
        if not files:
            raise FileNotFoundError(
                f"chunks glob '{chunks_val}' resolved to 0 files (base: {base})"
            )
        plan["chunks"] = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in files]

    merge_val = plan.get("merge")
    if isinstance(merge_val, str):
        merge_path = base / merge_val.removeprefix("./")
        if not merge_path.is_file():
            raise FileNotFoundError(f"merge: '{merge_val}' does not exist (base: {base})")
        plan["merge"] = yaml.safe_load(merge_path.read_text(encoding="utf-8"))

    return plan


__all__ = ["load_plan"]
