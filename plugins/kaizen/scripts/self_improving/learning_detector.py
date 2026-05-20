# consolidated-cli-parent: self-improving

"""kaizen learning-detector — content-based trigger for self-improving review.

Today the self-improving review nudge fires every N Stops — a counter
trigger that ignores whether there's anything worth reviewing. This
module replaces the counter trigger with a CONTENT signal: scan the
extraction pipeline for accumulated learning candidates and decide
whether the user should be nudged.

## Signals consumed

  - **brain Inbox drafts** (~/.claude/.kaizen/brain/Inbox/) — staged
    audit findings waiting for promotion via /kaizen:self-improving.
  - **kaizen-gold incidental discoveries** (~/.claude/.kaizen/gold/) —
    mid-session "ha!" captures the user marked durable.
  - **project-memory recent edits**
    (~/.claude/projects/<slug>/memory/) — files touched in the last
    N sessions are candidates for brain-promotion review.

Each signal is counted; the totals roll up to a single trigger
decision. Threshold defaults to 3 candidates across all signals.

## Public API

  ``find_learning_candidates(brain_root, since_days=7) -> list[dict]``
  ``should_trigger_review(candidates, min_count=3) -> bool``
  ``main(argv=None) -> int``  — CLI: scan [--since N_DAYS]
                                       [--threshold N]
                                       [--json]
                                       [--apply-hook-output]

## Distinct from neighbors

  - `brain_audit.py`    — DOES the session-end discovery (writes
                          drafts). This module READS those drafts.
  - `brain_promote.py`  — DOES the project-memory → brain promotion.
                          This module COUNTS the candidates.
  - `stop_self_improving_review.py` — the time/counter trigger this
                          module's output can supplement / replace.

## Closes BK-064.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent / "io"))

import _paths  # noqa: E402

# ─── Signal scanners ─────────────────────────────────────────────────

def _scan_inbox(brain_root: Path, since: _dt.datetime) -> list[dict]:
    """brain Inbox/ — drafts written by brain_audit awaiting promotion."""
    inbox = brain_root / "Inbox"
    if not inbox.is_dir():
        return []
    out = []
    for f in sorted(inbox.glob("*.md")):
        try:
            mtime = _dt.datetime.fromtimestamp(
                f.stat().st_mtime, _dt.timezone.utc
            )
        except OSError:
            continue
        if mtime < since:
            continue
        out.append({"signal": "inbox", "path": str(f), "mtime": mtime.isoformat()})
    return out

def _scan_gold(since: _dt.datetime) -> list[dict]:
    """kaizen-gold incidental discoveries."""
    gold_dir = Path(os.environ.get(
        "KAIZEN_GOLD_DIR", str(Path.home() / ".claude" / ".kaizen" / "gold")
    )).expanduser()
    if not gold_dir.is_dir():
        return []
    out = []
    for f in sorted(gold_dir.glob("**/*.md")):
        try:
            mtime = _dt.datetime.fromtimestamp(
                f.stat().st_mtime, _dt.timezone.utc
            )
        except OSError:
            continue
        if mtime < since:
            continue
        out.append({"signal": "gold", "path": str(f), "mtime": mtime.isoformat()})
    return out

def _scan_project_memory(since: _dt.datetime) -> list[dict]:
    """Project-memory entries touched recently — brain-promotion candidates."""
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return []
    out = []
    for project in base.iterdir():
        memory = project / "memory"
        if not memory.is_dir():
            continue
        for f in sorted(memory.glob("*.md")):
            if f.name == "MEMORY.md":
                continue  # index file, not a candidate
            try:
                mtime = _dt.datetime.fromtimestamp(
                    f.stat().st_mtime, _dt.timezone.utc
                )
            except OSError:
                continue
            if mtime < since:
                continue
            out.append({
                "signal": "project_memory",
                "path": str(f),
                "project": project.name,
                "mtime": mtime.isoformat(),
            })
    return out

# ─── Public API ──────────────────────────────────────────────────────

def find_learning_candidates(
    brain_root: Optional[Path] = None, since_days: int = 7
) -> list[dict]:
    """Aggregate candidates across the 3 signal sources.

    Returns one record per candidate with ``signal``, ``path``, ``mtime``
    keys. Sorted by mtime descending (newest first)."""
    brain_root = brain_root or _paths.BRAIN_DIR
    since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=since_days)
    out = _scan_inbox(brain_root, since) + _scan_gold(since) + _scan_project_memory(since)
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out

def should_trigger_review(candidates: list[dict], min_count: int = 3) -> bool:
    """Decide if the review nudge should fire.

    Default: any ≥ ``min_count`` total candidates across signals.
    Future: weight signals (gold > inbox > project_memory)."""
    return len(candidates) >= int(min_count)

def summarize(candidates: list[dict]) -> dict:
    """Per-signal count rollup for telemetry / human output."""
    out: dict[str, int] = {}
    for c in candidates:
        out[c["signal"]] = out.get(c["signal"], 0) + 1
    return {
        "total": len(candidates),
        "by_signal": dict(sorted(out.items())),
    }

# ─── CLI ─────────────────────────────────────────────────────────────

def _emit_json(payload: dict) -> None:
    sys.stdout.write(json.dumps({
        "data": payload,
        "kaizen": {
            "command": "learning_detector.py",
            "tool": "kaizen-learning-detector",
            "tool_version": "1.0.0",
            "schema_version": 1,
        },
    }, default=str, indent=2) + "\n")

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kaizen-learning-detector",
        description="Content-based trigger for self-improving review.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="scan for learning candidates")
    sc.add_argument("--since", type=int, default=7,
                    help="window in days (default 7)")
    sc.add_argument("--threshold", type=int, default=3,
                    help="trigger threshold (default 3)")
    sc.add_argument("--brain", type=Path, default=None,
                    help="brain root (default: $KAIZEN_BRAIN_DIR)")
    sc.add_argument("--json", action="store_true",
                    help="emit structured envelope")
    sc.add_argument("--apply-hook-output", action="store_true",
                    help="emit Stop-hook JSON for hook callers")
    args = ap.parse_args(argv)

    if os.environ.get("KAIZEN_LEARNING_DETECTOR_DISABLE") == "1":
        sys.stderr.write("kaizen-learning-detector: disabled\n")
        return 0

    candidates = find_learning_candidates(args.brain, since_days=args.since)
    trigger = should_trigger_review(candidates, min_count=args.threshold)
    summary = summarize(candidates)
    summary["trigger"] = trigger
    summary["threshold"] = args.threshold
    summary["since_days"] = args.since

    if args.apply_hook_output:
        # Emit Stop-hook hookSpecificOutput format (matches the
        # convention used by stop_self_improving_review.py for the
        # surface mechanism. Silent when below threshold.)
        if trigger:
            msg = (f"💡 {summary['total']} learning candidate(s) accumulated "
                   f"({summary['by_signal']}) — consider running "
                   f"/kaizen:self-improving review")
            sys.stdout.write(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "systemMessage": msg,
                },
            }) + "\n")
        return 0

    if args.json:
        _emit_json({"candidates": candidates, "summary": summary})
        return 0

    sys.stdout.write(f"learning-detector: {summary['total']} candidates "
                     f"in last {args.since}d (threshold={args.threshold})\n")
    for sig, n in summary["by_signal"].items():
        sys.stdout.write(f"  {sig}: {n}\n")
    sys.stdout.write(f"trigger: {'YES' if trigger else 'no'}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
