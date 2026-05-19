#!/usr/bin/env python3
"""kaizen-md-link-rot — markdown link-rot scanner.

Walks `*.md` files under a root, extracts `[label](relative)` links,
and flags those whose relative target doesn't resolve on disk.
Absolute URLs (http*) and mailto/anchors are skipped.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-md-link-rot", tool_version="1.0.0")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\n]+)\)")


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def _is_resolvable(target: str) -> bool:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return True
    return False


def scan(*, root: Path) -> dict:
    if not root.is_dir():
        return {"md_total": 0, "broken": []}
    mds = sorted(root.rglob("*.md"))
    broken: list[dict] = []
    for md in mds:
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _LINK_RE.finditer(text):
            target = m.group(2).strip().split("#", 1)[0]
            if not target:
                continue
            if _is_resolvable(target):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                broken.append({
                    "from":   str(md.relative_to(root)),
                    "target": target,
                })
    return {"md_total": len(mds), "broken": broken,
            "broken_count": len(broken)}


def _run(args) -> int:
    rep = scan(root=Path(args.root).expanduser() if args.root else _plugin_root().parent)
    n = len(rep["broken"])
    verdict = "green" if n == 0 else ("yellow" if n <= 10 else "red")
    if args.cmd == "gaps" and not args.json:
        for b in rep["broken"]:
            print(f"{b['from']} → {b['target']}")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"broken": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-md-link-rot",
        description="Find broken relative markdown links.")
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
