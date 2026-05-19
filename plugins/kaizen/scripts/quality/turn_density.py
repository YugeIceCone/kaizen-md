#!/usr/bin/env python3
"""kaizen-turn-density — events-per-turn rollup over the trace JSONL.

A "turn" is bounded by a UserPromptSubmit event. High density (many
tool calls per turn) often signals tool-chain runaway or context
pressure; low density signals under-utilized turns.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-turn-density", tool_version="1.0.0")
_DEFAULT_LOG = Path.home() / ".claude/.kaizen/trace/events.jsonl"


def scan(*, trace_log: Path) -> dict:
    if not trace_log.is_file():
        return {"turns": {}, "events_seen": 0,
                "note": f"trace log not found: {trace_log}"}
    turns: dict[int, dict] = {}
    total = 0
    for line in trace_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        t = ev.get("turn")
        if t is None:
            continue
        slot = turns.setdefault(int(t), {"events": 0, "tool_uses": 0})
        slot["events"] += 1
        if ev.get("event") == "ToolUse":
            slot["tool_uses"] += 1
    return {"turns": turns, "events_seen": total,
            "turn_count": len(turns)}


def _run(args) -> int:
    log = Path(args.trace_log).expanduser() if args.trace_log else _DEFAULT_LOG
    rep = scan(trace_log=log)
    if args.cmd == "gaps" and not args.json:
        if rep.get("note"):
            print(rep["note"])
        for t in sorted(rep["turns"]):
            slot = rep["turns"][t]
            print(f"turn {t}: {slot['events']} events ({slot['tool_uses']} tool calls)")
        return 0
    _emit(rep, verdict="green",
          counts={"turns": len(rep["turns"]), "events": rep["events_seen"]})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-turn-density",
        description="Per-turn event-density rollup over trace JSONL.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--trace-log", default=None)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
