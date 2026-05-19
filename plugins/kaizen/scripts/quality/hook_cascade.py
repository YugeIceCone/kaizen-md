#!/usr/bin/env python3
"""kaizen-hook-cascade — find hooks that consistently fire together.

Walks the trace JSONL and counts hook-pairs whose fire timestamps
fall within `--window-seconds` of each other. High co-occurrence
counts surface implicit hook chains the user may want to consolidate
or document.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-hook-cascade", tool_version="1.0.0")
_DEFAULT_LOG = Path.home() / ".claude/.kaizen/trace/events.jsonl"


def scan(*, trace_log: Path, window_seconds: int = 2) -> dict:
    if not trace_log.is_file():
        return {"cascades": [], "events_seen": 0,
                "note": f"trace log not found: {trace_log}"}
    fires: list[tuple[float, str]] = []
    for line in trace_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") in ("hook_fired", "hook") and "ts_epoch" in ev:
            fires.append((float(ev["ts_epoch"]), str(ev.get("hook", "unknown"))))
    fires.sort()
    counter: Counter[tuple[str, str]] = Counter()
    for i, (ts_a, hook_a) in enumerate(fires):
        for j in range(i + 1, len(fires)):
            ts_b, hook_b = fires[j]
            if ts_b - ts_a > window_seconds:
                break
            if hook_a == hook_b:
                continue
            pair = tuple(sorted((hook_a, hook_b)))
            counter[pair] += 1
    cascades = [{"a": p[0], "b": p[1], "count": c}
                for p, c in counter.most_common() if c >= 2]
    return {"cascades": cascades, "events_seen": len(fires),
            "pair_count": len(cascades)}


def _run(args) -> int:
    log = Path(args.trace_log).expanduser() if args.trace_log else _DEFAULT_LOG
    rep = scan(trace_log=log, window_seconds=args.window_seconds)
    n = len(rep["cascades"])
    if args.cmd == "gaps" and not args.json:
        if rep.get("note"):
            print(rep["note"])
        for c in rep["cascades"]:
            print(f"{c['count']:4d}  {c['a']} ↔ {c['b']}")
        return 0
    _emit(rep, verdict="green", counts={"cascades": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-hook-cascade",
        description="Detect hooks that consistently fire together.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--trace-log", default=None)
        s.add_argument("--window-seconds", type=int, default=2)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
