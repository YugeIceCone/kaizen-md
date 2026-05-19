"""kaizen-observer-events — read-side CLI for the observer events.jsonl sink.

Distinct from kaizen-observe (the 6-layer observability tool at
skills/workflow/scripts/observe.py). This CLI specifically queries the
custom-observer sink built in Phase 1+1.5 (capture hook + ingest module).

Closes the observer's read surface (Phase 1.6): events captured by
posttool-observer-capture.sh are queryable here.

Subcommands:
  recent [--n N] [--json]
      Last N events (default 10). Default output: one line per event;
      --json returns the raw envelope array.
  stats  [--json]
      Counts per event_kind + per tool. Default: human-readable lines;
      --json returns {"total": N, "by_event_kind": {...}, "by_tool": {...}}.
  filter [--tool T] [--source S] [--n N] [--json]
      Selective query. All filters AND. --n caps output size.

Iron-laws:
  - READ-ONLY — never writes the sink.
  - Graceful on missing sink (returns empty / []).
  - Skips malformed JSONL lines (line-by-line tolerance).
  - Env-overridable sink via KAIZEN_OBSERVER_DIR.

Design contract (same family as observer capture, kaizen-progress,
kaizen-learn, etc.):
  - PROGRAMMABLE — pure functions (load_events, compute_stats);
                   CLI is a thin shell over them.
  - REPRODUCIBLE — same sink + same args → same output.
  - CONSISTENT   — env-overridable, --json flag, exit 0 on success.
  - DETERMINISTIC — no time-of-day branching.
  - REUSABLE     — load_events callable directly from other modules.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _observer_dir() -> Path:
    # DRY — delegates to shared _paths.env_overridable_dir helper.
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here.parent / "io"))
    from _paths import env_overridable_dir
    return env_overridable_dir("KAIZEN_OBSERVER_DIR", "observer")


def _sink_path() -> Path:
    return _observer_dir() / "events.jsonl"


def load_events() -> list[dict[str, Any]]:
    """Read all events from the sink. Missing file → []."""
    p = _sink_path()
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(evt, dict):
            out.append(evt)
    return out


def compute_stats(events: list[dict]) -> dict[str, Any]:
    """Per-event_kind + per-tool counts + total."""
    by_kind = Counter(e.get("event_kind", "") for e in events)
    by_tool = Counter(e.get("tool", "") for e in events)
    # Drop empty-string keys (events without those fields)
    by_kind.pop("", None)
    by_tool.pop("", None)
    return {
        "total": len(events),
        "by_event_kind": dict(by_kind),
        "by_tool": dict(by_tool),
    }


def _render_event_line(evt: dict) -> str:
    return (f"[{evt.get('ts', '?')}] {evt.get('event_kind', '?')} "
             f"src={evt.get('source', '?')} "
             f"tool={evt.get('tool', '?')} "
             f"sid={evt.get('sid', '?')[:8]}")


def _cmd_recent(args) -> int:
    events = load_events()
    last = events[-args.n:] if args.n > 0 else []
    if args.json:
        print(json.dumps(last))
    else:
        for e in last:
            print(_render_event_line(e))
    return 0


def _cmd_stats(args) -> int:
    events = load_events()
    stats = compute_stats(events)
    if args.json:
        print(json.dumps(stats))
    else:
        print(f"total: {stats['total']}")
        print("by_event_kind:")
        for k, v in sorted(stats["by_event_kind"].items()):
            print(f"  {k}: {v}")
        print("by_tool:")
        for k, v in sorted(stats["by_tool"].items()):
            print(f"  {k}: {v}")
    return 0


def _cmd_filter(args) -> int:
    events = load_events()
    out = []
    for e in events:
        if args.tool and e.get("tool") != args.tool:
            continue
        if args.source and e.get("source") != args.source:
            continue
        out.append(e)
    if args.n > 0:
        out = out[-args.n:]
    if args.json:
        print(json.dumps(out))
    else:
        for e in out:
            print(_render_event_line(e))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-observer-events",
        description="Read-side CLI for the observer events.jsonl sink.",
    )
    sub = p.add_subparsers(dest="command")

    pr = sub.add_parser("recent", help="last N events (default 10)")
    pr.add_argument("--n", type=int, default=10)
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(fn=_cmd_recent)

    ps = sub.add_parser("stats", help="counts per event_kind + per tool")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(fn=_cmd_stats)

    pf = sub.add_parser("filter", help="filter by tool / source")
    pf.add_argument("--tool", default=None)
    pf.add_argument("--source", default=None,
                     choices=["parent", "subagent", "slash", "mcp", "hook"])
    pf.add_argument("--n", type=int, default=0,
                     help="cap output size (0 = no cap)")
    pf.add_argument("--json", action="store_true")
    pf.set_defaults(fn=_cmd_filter)

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
