#!/usr/bin/env python3
"""kaizen-complexity — radon cc cyclomatic-complexity wrapper.

Optional dep — `is_available()` returns False when radon isn't installed.
Otherwise runs `radon cc -j` and surfaces functions above the threshold.
Subcommands: report | gaps.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-complexity", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def is_available() -> bool:
    try:
        import radon  # noqa: F401
        return True
    except ImportError:
        return False


def scan(*, target: Path, min_grade: str = "C") -> dict:
    if not is_available():
        return {"available": False, "findings": [],
                "note": "radon not installed — `pip install radon`"}
    args = ["radon", "cc", "-j", "-n", min_grade, str(target)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"available": True, "findings": [], "error": str(exc)}
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {"available": True, "findings": [],
                "error": f"radon emitted non-JSON: {r.stdout[:200]}"}
    findings: list[dict] = []
    for path, items in data.items():
        for it in items or []:
            findings.append({"path": path, "name": it.get("name"),
                              "type": it.get("type"), "rank": it.get("rank"),
                              "complexity": it.get("complexity"),
                              "lineno": it.get("lineno")})
    return {"available": True, "findings": findings}


def _run(args) -> int:
    rep = scan(target=Path(args.target).expanduser(),
                min_grade=args.min_grade)
    n = len(rep["findings"])
    if not rep["available"]:
        verdict = "yellow"
    else:
        verdict = "green" if n == 0 else ("yellow" if n <= 20 else "red")
    if args.cmd == "gaps" and not args.json:
        if not rep["available"]:
            print(rep.get("note", "radon unavailable"))
            return 0
        for f in rep["findings"]:
            print(f"{f['path']}:{f['lineno']}  [{f['rank']} cc={f['complexity']}]  "
                  f"{f['type']} {f['name']}")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-complexity",
        description="Radon cyclomatic-complexity wrapper.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--target", default=str(_plugin_root() / "skills/workflow/scripts"))
        s.add_argument("--min-grade", default="C",
            help="Filter at A..F (radon -n). Default C (10+ complexity).")
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
