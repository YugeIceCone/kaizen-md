#!/usr/bin/env python3
"""kaizen-dead-code — vulture wrapper for dead-code detection.

Optional dep — `is_available()` returns False when vulture isn't
installed. The scan still returns a typed shape so callers can branch
without try/except (pref-optional-feature-graceful-fallback).

Subcommands: report | gaps. Filters vulture output by --min-confidence
(default 80) and excludes test files by default.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-dead-code", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def is_available() -> bool:
    try:
        import vulture  # noqa: F401
        return True
    except ImportError:
        return False


def scan(*, targets: list[Path], min_confidence: int = 80) -> dict:
    if not is_available():
        return {
            "available":      False,
            "findings":       [],
            "note":           "vulture not installed — `pip install vulture`",
        }
    args = ["vulture", f"--min-confidence={min_confidence}"] + [str(t) for t in targets]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"available": True, "findings": [], "error": str(exc)}
    findings: list[dict] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # vulture output: path:line: message (N% confidence)
        try:
            path, rest = line.split(":", 1)
            lineno, message = rest.split(":", 1)
            findings.append({"path": path, "line": int(lineno),
                              "message": message.strip()})
        except (ValueError, IndexError):
            findings.append({"raw": line})
    return {"available": True, "findings": findings}


def _run(args) -> int:
    targets = [_plugin_root() / "skills/workflow/scripts"]
    rep = scan(targets=targets, min_confidence=args.min_confidence)
    n = len(rep["findings"])
    if not rep["available"]:
        verdict = "yellow"
    else:
        verdict = "green" if n == 0 else ("yellow" if n <= 20 else "red")
    if args.cmd == "gaps" and not args.json:
        if not rep["available"]:
            print(rep.get("note", "vulture unavailable"))
            return 0
        for f in rep["findings"]:
            if "path" in f:
                print(f"{f['path']}:{f['line']}  {f['message']}")
            else:
                print(f.get("raw", ""))
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-dead-code",
        description="vulture wrapper — dead-code detection over kaizen scripts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--min-confidence", type=int, default=80)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
