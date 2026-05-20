#!/usr/bin/env python3
"""kaizen-todo-inventory — list TODO/FIXME/HACK/XXX markers with file:line refs.

Walks source files under root (default: kaizen-md repo root) and
surfaces every marker so the user can triage / age them via git blame.
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

_emit = _envelope.emitter("kaizen-todo-inventory", tool_version="1.0.0")
_MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b[:\s]?(.*)")
_DEFAULT_GLOB = ("*.py", "*.sh", "*.md")

def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]

def scan(*, root: Path, globs=_DEFAULT_GLOB) -> dict:
    if not root.is_dir():
        return {"findings": [], "count": 0}
    findings: list[dict] = []
    for g in globs:
        for p in root.rglob(g):
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                m = _MARKER_RE.search(line)
                if m:
                    findings.append({
                        "path": str(p.relative_to(root)), "line": i,
                        "kind": m.group(1),
                        "text": m.group(2).strip()[:120],
                    })
    return {"findings": findings, "count": len(findings)}

def _run(args) -> int:
    root = Path(args.root).expanduser() if args.root else _plugin_root().parent
    rep = scan(root=root)
    n = rep["count"]
    verdict = "green" if n == 0 else ("yellow" if n <= 50 else "red")
    if args.cmd == "gaps" and not args.json:
        for f in rep["findings"][:200]:
            print(f"{f['path']}:{f['line']}  [{f['kind']}] {f['text']}")
        return 0
    _emit(rep, verdict=verdict, counts={"todos": n})
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-todo-inventory",
        description="TODO/FIXME/HACK/XXX marker inventory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--root", default=None)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
