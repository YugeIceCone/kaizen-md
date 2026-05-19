#!/usr/bin/env python3
"""kaizen-prompt-event-diff — slice the trace log by UserPromptSubmit
boundaries. For each slice (one user prompt → next user prompt),
report event counts + breakdown by tool/event name.

Use case: "what happened in turn N?" or "what blew up between my
last two prompts?"
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

_emit = _envelope.emitter("kaizen-prompt-event-diff", tool_version="1.0.0")
_DEFAULT_LOG = Path.home() / ".claude/.kaizen/trace/events.jsonl"


def slice_by_prompt(*, trace_log: Path) -> list[dict]:
    if not trace_log.is_file():
        return []
    events: list[dict] = []
    for line in trace_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(ev)
    slices: list[dict] = []
    current: dict | None = None
    for ev in events:
        if ev.get("event") == "UserPromptSubmit":
            if current is not None:
                slices.append(current)
            current = {"prompt_ts": ev.get("ts_epoch"), "events": [],
                        "event_count": 0, "by_type": {}}
        elif current is not None:
            current["events"].append(ev)
            current["event_count"] += 1
            key = ev.get("name") or ev.get("event") or "unknown"
            current["by_type"][key] = current["by_type"].get(key, 0) + 1
    if current is not None:
        slices.append(current)
    return slices


def _run(args) -> int:
    log = Path(args.trace_log).expanduser() if args.trace_log else _DEFAULT_LOG
    slices = slice_by_prompt(trace_log=log)
    if args.cmd == "gaps" and not args.json:
        if not slices:
            print(f"no slices (log: {log})")
            return 0
        for i, s in enumerate(slices, 1):
            print(f"prompt {i} (ts={s['prompt_ts']}) → {s['event_count']} events: "
                  + ", ".join(f"{k}={v}" for k, v in s["by_type"].items()))
        return 0
    summary = {"slices_count": len(slices),
                "slices": [{"prompt_ts": s["prompt_ts"],
                             "event_count": s["event_count"],
                             "by_type": s["by_type"]} for s in slices]}
    _emit(summary, verdict="green", counts={"slices": len(slices)})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-prompt-event-diff",
        description="Slice trace events by UserPromptSubmit boundaries.")
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
