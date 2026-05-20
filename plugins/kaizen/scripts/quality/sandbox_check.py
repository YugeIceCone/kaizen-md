#!/usr/bin/env python3
"""kaizen-test-isolation — AST scan for sandboxing violations in tests/.

Three rules:
  - hardcoded-home    — string literal starts with `/home/`
  - expanduser-claude — `Path("~/.claude/...").expanduser()` or similar
  - env-mutation      — `os.environ["KAIZEN_..."] = ...` at module/test scope
                        (the canonical pattern is `--KAIZEN_<X>_PATH=<tmp>`
                        sandboxing or context-manager-scoped mutation)

Findings are advisory — real tests sometimes need these patterns
(graceful-skip checks for `/home/cherry86/.../granite4.1:8b`, etc).
The output is intended as a triage list, not a hard gate.

Stdlib `ast` only.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-sandbox-check", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.findings: list[dict] = []
        self.path = path

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            if node.value.startswith("/home/"):
                self.findings.append({
                    "rule": "hardcoded-home", "path": self.path,
                    "line": node.lineno, "text": node.value[:60],
                })
            elif node.value.startswith("~/.claude"):
                self.findings.append({
                    "rule": "expanduser-claude", "path": self.path,
                    "line": node.lineno, "text": node.value[:60],
                })

    def visit_Assign(self, node: ast.Assign):
        # os.environ["KAIZEN_FOO"] = "..."
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            v = target.value
            if (isinstance(v, ast.Attribute) and v.attr == "environ"
                    and isinstance(v.value, ast.Name) and v.value.id == "os"):
                idx = target.slice
                key = None
                if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
                    key = idx.value
                if key and key.startswith("KAIZEN_"):
                    self.findings.append({
                        "rule": "env-mutation", "path": self.path,
                        "line": node.lineno, "text": f"os.environ[{key!r}] = ...",
                    })
        self.generic_visit(node)


def scan_text(source: str, *, path: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    v = _Visitor(path)
    v.visit(tree)
    return v.findings


def scan(*, tests_dir: Path) -> dict:
    findings: list[dict] = []
    tests = sorted(tests_dir.glob("test_*.py"))
    for t in tests:
        try:
            text = t.read_text(encoding="utf-8")
        except OSError:
            continue
        for f in scan_text(text, path=str(t.relative_to(_plugin_root()))):
            findings.append(f)
    return {
        "tests_total":     len(tests),
        "findings":        findings,
        "violation_count": len(findings),
    }


def _run(args) -> int:
    rep = scan(tests_dir=_plugin_root() / "tests")
    n = rep["violation_count"]
    verdict = "green" if n == 0 else ("yellow" if n <= 20 else "red")
    if args.cmd == "gaps" and not args.json:
        for f in rep["findings"]:
            print(f"{f['path']}:{f['line']}  [{f['rule']}]  {f['text']}")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-sandbox-check",
        description="AST scan for sandboxing violations in tests/.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
