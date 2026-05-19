#!/usr/bin/env python3
"""kaizen-test-density — public-function count per script vs the
paired-test test-method count. Low density (lots of functions, few
tests) flags under-tested modules.

Public = top-level `def` not prefixed with `_`. Test method = any
`def test_*` inside any class in tests/test_<script>.py.
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

_emit = _envelope.emitter("kaizen-test-density", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _public_funcs(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                count += 1
    return count


def _test_methods(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for fn in cls.body:
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if fn.name.startswith("test_"):
                    count += 1
    return count


def scan(*, plugin_root: Path) -> dict:
    scripts_dir = plugin_root / "skills/workflow/scripts"
    tests_dir = plugin_root / "tests"
    per_script: list[dict] = []
    if not scripts_dir.is_dir():
        return {"per_script": [], "low_density": []}
    for s in sorted(scripts_dir.glob("*.py")):
        if s.name.startswith("_"):
            continue
        try:
            src = s.read_text(encoding="utf-8")
        except OSError:
            continue
        pub = _public_funcs(src)
        if pub == 0:
            continue
        test_path = tests_dir / f"test_{s.name}"
        tests = 0
        if test_path.is_file():
            try:
                tests = _test_methods(test_path.read_text(encoding="utf-8"))
            except OSError:
                tests = 0
        per_script.append({
            "script": s.name, "public_funcs": pub, "test_methods": tests,
            "ratio": round(tests / pub, 2) if pub else 0.0,
        })
    low = [r for r in per_script if r["ratio"] < 0.5]
    return {"per_script": per_script, "low_density": low,
            "low_density_count": len(low)}


def _run(args) -> int:
    rep = scan(plugin_root=_plugin_root())
    n = len(rep["low_density"])
    verdict = "green" if n == 0 else ("yellow" if n <= 10 else "red")
    if args.cmd == "gaps" and not args.json:
        for r in rep["low_density"]:
            print(f"{r['script']}  pub={r['public_funcs']} tests={r['test_methods']} ratio={r['ratio']}")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"low_density": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-test-density",
        description="Public-function vs test-method density per script.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
