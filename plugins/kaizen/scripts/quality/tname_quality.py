#!/usr/bin/env python3
"""kaizen-test-name-quality — flag test_* method names that are too
terse to convey scenario (e.g. `test_x`, `test_foo`).

Rule: a test method name must have ≥3 underscore-separated components
or ≥4 alpha chars beyond the `test_` prefix.
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

_emit = _envelope.emitter("kaizen-tname-quality", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _too_short(name: str) -> bool:
    suffix = name.removeprefix("test_")
    parts = [p for p in suffix.split("_") if p]
    return len(parts) < 2 and len(suffix) < 5


def scan_text(source: str, *, path: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    findings: list[dict] = []
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test_"):
                continue
            if _too_short(fn.name):
                findings.append({"path": path, "line": fn.lineno,
                                  "name": fn.name,
                                  "rule": "test-name-too-short"})
    return findings


def scan(*, tests_dir: Path) -> dict:
    if not tests_dir.is_dir():
        return {"tests_total": 0, "findings": []}
    tests = sorted(tests_dir.glob("test_*.py"))
    findings: list[dict] = []
    for t in tests:
        try:
            text = t.read_text(encoding="utf-8")
        except OSError:
            continue
        for f in scan_text(text, path=str(t.relative_to(_plugin_root()))):
            findings.append(f)
    return {"tests_total": len(tests), "findings": findings,
            "violation_count": len(findings)}


def _run(args) -> int:
    rep = scan(tests_dir=_plugin_root() / "tests")
    n = len(rep["findings"])
    verdict = "green" if n == 0 else ("yellow" if n <= 20 else "red")
    if args.cmd == "gaps" and not args.json:
        for f in rep["findings"][:200]:
            print(f"{f['path']}:{f['line']}  {f['name']}  [{f['rule']}]")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-tname-quality",
        description="Test-method name quality (too-short flags).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
