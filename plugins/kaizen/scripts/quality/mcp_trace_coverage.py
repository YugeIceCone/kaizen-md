#!/usr/bin/env python3
"""kaizen-mcp-trace-coverage — every *_mcp.py SHOULD emit kaizen-trace
events so per-tool MCP calls are observable. Detected by presence of
`_trace`, `emit_trace`, `kaizen-trace`, or `_envelope` import patterns.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-mcp-trace-coverage", tool_version="1.0.0")
_TRACE_PATTERNS = (
    re.compile(r"\bfrom\s+_trace\b"),
    re.compile(r"\bimport\s+_trace\b"),
    re.compile(r"\bemit_trace\b"),
    re.compile(r"\bkaizen-trace\b"),
    re.compile(r"\b_envelope\b"),
)

def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]

def scan(*, scripts_dir: Path) -> dict:
    if not scripts_dir.is_dir():
        return {"mcp_total": 0, "gaps": [], "coverage_pct": 100.0}
    mcps = sorted(scripts_dir.glob("*_mcp.py"))
    gaps = []
    for m in mcps:
        try:
            text = m.read_text(encoding="utf-8")
        except OSError:
            continue
        if not any(p.search(text) for p in _TRACE_PATTERNS):
            gaps.append({"module": m.name})
    return {
        "mcp_total":    len(mcps),
        "gaps":         gaps,
        "coverage_pct": round(
            100.0 * (len(mcps) - len(gaps)) / max(len(mcps), 1), 2,
        ),
    }

def _run(args) -> int:
    rep = scan(scripts_dir=_plugin_root() / "scripts/mcp")
    n = len(rep["gaps"])
    verdict = "green" if n == 0 else ("yellow" if n <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for g in rep["gaps"]:
            print(g["module"])
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": n})
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-mcp-trace-coverage",
        description="Audit *_mcp.py for trace-event emission.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
