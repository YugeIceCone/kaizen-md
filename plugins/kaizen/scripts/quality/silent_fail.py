#!/usr/bin/env python3
"""kaizen-silent-fail — scan the trace log for hooks that fired but
returned empty output (a silent failure pattern: the hook ran, didn't
crash, but did nothing visible — usually a logic bug, a missing
dependency that the hook swallowed, or an early-exit knob misfiring).

Reads kaizen-trace JSONL events. Groups by hook. Flags hooks whose
fire rate has > THRESHOLD % empty-output events.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-silent-fail", tool_version="1.0.0")
_DEFAULT_TRACE_LOG = Path.home() / ".claude/.kaizen/trace/events.jsonl"
_THRESHOLD_PCT = 50.0


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _hook_fire_events(trace_log: Path):
    if not trace_log.is_file():
        return
    for line in trace_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") in ("hook_fired", "hook"):
            yield ev


def scan(*, trace_log: Path, threshold_pct: float = _THRESHOLD_PCT) -> dict:
    if not trace_log.is_file():
        return {"findings": [], "hooks_seen": 0, "events_seen": 0,
                "note": f"trace log not found: {trace_log}"}
    by_hook: dict[str, list[int]] = {}
    total = 0
    for ev in _hook_fire_events(trace_log):
        h = ev.get("hook") or ev.get("name") or "unknown"
        out_len = int(ev.get("stdout_len", 0) or 0)
        by_hook.setdefault(h, []).append(out_len)
        total += 1
    findings: list[dict] = []
    for hook, lens in by_hook.items():
        empties = sum(1 for n in lens if n == 0)
        pct = (100.0 * empties / len(lens)) if lens else 0.0
        if pct >= threshold_pct and empties >= 2:
            findings.append({"hook": hook, "fires": len(lens),
                              "empties": empties, "pct_empty": round(pct, 2)})
    return {"findings": findings, "hooks_seen": len(by_hook),
            "events_seen": total}


def _run(args) -> int:
    log = Path(args.trace_log).expanduser() if args.trace_log else _DEFAULT_TRACE_LOG
    rep = scan(trace_log=log, threshold_pct=args.threshold)
    n = len(rep["findings"])
    verdict = "green" if n == 0 else ("yellow" if n <= 3 else "red")
    if args.cmd == "gaps" and not args.json:
        if rep.get("note"):
            print(rep["note"])
        for f in rep["findings"]:
            print(f"{f['hook']}  empties={f['empties']}/{f['fires']}  "
                  f"({f['pct_empty']}% silent)")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-silent-fail",
        description="Detect hooks that fire but return no output.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--trace-log", default=None)
        s.add_argument("--threshold", type=float, default=_THRESHOLD_PCT)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
