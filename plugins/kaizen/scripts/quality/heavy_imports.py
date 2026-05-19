#!/usr/bin/env python3
"""kaizen-heavy-imports — AST scan for eager (module-level) imports
of heavy dependencies (torch / transformers / tree_sitter / etc.).

Heavy deps should lazy-load inside functions/methods (the
pref-optional-feature-graceful-fallback pattern) so the default
install stays light.
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

_emit = _envelope.emitter("kaizen-heavy-imports", tool_version="1.0.0")
_HEAVY_MODULES = {
    "torch", "transformers", "sentence_transformers", "tree_sitter",
    "spacy", "tensorflow", "pyarrow", "duckdb", "vulture", "radon",
    "ollama", "scrapegraphai", "playwright", "selenium", "openai",
    "anthropic",
}


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def scan_text(source: str, *, path: str) -> list[dict]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    findings: list[dict] = []
    for node in tree.body:  # module-level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _HEAVY_MODULES:
                    findings.append({"path": path, "line": node.lineno,
                                      "module": top})
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _HEAVY_MODULES:
                findings.append({"path": path, "line": node.lineno,
                                  "module": top})
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
            print(f"{f['path']}:{f['line']}  eager import of {f['module']}")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-heavy-imports",
        description="AST scan for eager imports of heavy deps.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
