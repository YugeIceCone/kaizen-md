#!/usr/bin/env python3
"""kaizen-subprocess-rc — AST scan for subprocess.run / subprocess.call
invocations whose return value is silently dropped (no assignment,
no check=True). Silent rc drops are the classic source of
"the command failed but the script continued" bugs.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-subprocess-rc", tool_version="1.0.0")
_TARGETS = {"run", "call", "check_output", "Popen"}


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _is_subprocess_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id == "subprocess" and f.attr in _TARGETS
    return False


def _has_check_true(call: ast.Call) -> bool:
    for k in call.keywords:
        if k.arg == "check" and isinstance(k.value, ast.Constant) and k.value.value is True:
            return True
    return False


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.findings: list[dict] = []

    def visit_Expr(self, node: ast.Expr):
        if isinstance(node.value, ast.Call) and _is_subprocess_call(node.value):
            if not _has_check_true(node.value):
                self.findings.append({"path": self.path, "line": node.lineno,
                                       "call": node.value.func.attr})
        self.generic_visit(node)


def scan_text(source: str, *, path: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    v = _Visitor(path)
    v.visit(tree)
    return v.findings


def scan(*, scripts_dir: Path) -> dict:
    scripts = sorted(scripts_dir.glob("*.py")) if scripts_dir.is_dir() else []
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
            print(f"{f['path']}:{f['line']}  subprocess.{f['call']} rc dropped")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-subprocess-rc",
        description="AST scan for unchecked subprocess return values.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
