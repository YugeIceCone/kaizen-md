#!/usr/bin/env python3
"""kaizen-var-name-quality — flag single-letter / too-short variable
names at module scope (locals in functions are fine — common loop
counters, math vars)."""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-var-name-quality", tool_version="1.0.0")

def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]

def scan_text(source: str, *, path: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    findings: list[dict] = []
    for node in tree.body:  # module-level only
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name) and len(t.id) == 1:
                findings.append({"path": path, "line": node.lineno,
                                  "name": t.id, "rule": "single-letter-module-var"})
    return findings

def scan(*, scripts_dir: Path) -> dict:
    if not scripts_dir.is_dir():
        return {"scripts_total": 0, "findings": []}
    scripts = sorted(scripts_dir.glob("*.py"))
    findings: list[dict] = []
    for s in scripts:
        try:
            text = s.read_text(encoding="utf-8")
        except OSError:
            continue
        for f in scan_text(text, path=str(s.relative_to(_plugin_root()))):
            findings.append(f)
    return {"scripts_total": len(scripts), "findings": findings,
            "violation_count": len(findings)}

def _run(args) -> int:
    rep = scan(scripts_dir=_plugin_root() / "skills/workflow/scripts")
    n = len(rep["findings"])
    verdict = "green" if n == 0 else ("yellow" if n <= 5 else "red")
    if args.cmd == "gaps" and not args.json:
        for f in rep["findings"]:
            print(f"{f['path']}:{f['line']}  {f['name']!r}  [{f['rule']}]")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-var-name-quality",
        description="Module-level variable name quality.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
