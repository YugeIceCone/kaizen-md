#!/usr/bin/env python3
"""kaizen-prompt-rhythm — time between UserPromptSubmit events.

Surfaces user cadence: long intervals = thinking / paused, short
intervals = rapid-fire / debugging. Mean/median + raw list.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-prompt-rhythm", tool_version="1.0.0")
_DEFAULT_LOG = Path.home() / ".claude/.kaizen/trace/events.jsonl"


def scan(*, trace_log: Path) -> dict:
    if not trace_log.is_file():
        return {"intervals_seconds": [], "mean_seconds": 0.0,
                "median_seconds": 0.0,
                "note": f"trace log not found: {trace_log}"}
    timestamps: list[float] = []
    for line in trace_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "UserPromptSubmit" and "ts_epoch" in ev:
            timestamps.append(float(ev["ts_epoch"]))
    timestamps.sort()
    intervals = [int(timestamps[i] - timestamps[i - 1])
                 for i in range(1, len(timestamps))]
    return {
        "intervals_seconds": intervals,
        "mean_seconds":   round(statistics.mean(intervals), 2) if intervals else 0.0,
        "median_seconds": round(statistics.median(intervals), 2) if intervals else 0.0,
        "prompt_count":   len(timestamps),
    }


def _run(args) -> int:
    log = Path(args.trace_log).expanduser() if args.trace_log else _DEFAULT_LOG
    rep = scan(trace_log=log)
    if args.cmd == "gaps" and not args.json:
        if rep.get("note"):
            print(rep["note"])
        print(f"prompts={rep.get('prompt_count', 0)}  "
              f"mean={rep['mean_seconds']}s  median={rep['median_seconds']}s")
        return 0
    _emit(rep, verdict="green",
          counts={"prompts": rep.get("prompt_count", 0)})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-prompt-rhythm",
        description="Time between UserPromptSubmit events.")
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
