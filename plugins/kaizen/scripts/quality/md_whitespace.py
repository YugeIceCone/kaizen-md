#!/usr/bin/env python3
"""kaizen-md-whitespace — trailing whitespace + tab-indent scanner for *.md files."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "io"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-md-whitespace", tool_version="1.0.0")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def scan_text(text: str, *, path: str) -> list[dict]:
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        if line != line.rstrip():
            findings.append({"path": path, "line": i, "rule": "trailing-whitespace"})
        if line.startswith("\t"):
            findings.append({"path": path, "line": i, "rule": "tab-indent"})
    return findings


def scan(*, root: Path) -> dict:
    if not root.is_dir():
        return {"md_total": 0, "findings": []}
    mds = sorted(root.rglob("*.md"))
    findings: list[dict] = []
    for md in mds:
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for f in scan_text(text, path=str(md.relative_to(root))):
            findings.append(f)
    return {"md_total": len(mds), "findings": findings,
            "violation_count": len(findings)}


def _run(args) -> int:
    root = Path(args.root).expanduser() if args.root else _plugin_root().parent
    rep = scan(root=root)
    n = len(rep["findings"])
    verdict = "green" if n == 0 else ("yellow" if n <= 50 else "red")
    if args.cmd == "gaps" and not args.json:
        for f in rep["findings"][:200]:
            print(f"{f['path']}:{f['line']}  [{f['rule']}]")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-md-whitespace",
        description="Trailing whitespace + tab indent in *.md.")
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
