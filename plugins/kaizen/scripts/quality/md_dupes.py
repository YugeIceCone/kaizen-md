#!/usr/bin/env python3
"""kaizen-md-dupes — flag duplicate heading text within one *.md file."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — legacy helpers still at skills/workflow/scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "workflow" / "scripts"))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-md-dupes", tool_version="1.0.0")
_H_RE = re.compile(r"^#+\s+(.+?)\s*$", re.MULTILINE)


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[1]


def scan_text(text: str, *, path: str) -> list[dict]:
    headings = [m.group(1).strip() for m in _H_RE.finditer(text)]
    counts = Counter(headings)
    return [{"path": path, "heading": h, "count": c}
            for h, c in counts.items() if c > 1]


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
    verdict = "green" if n == 0 else ("yellow" if n <= 20 else "red")
    if args.cmd == "gaps" and not args.json:
        for f in rep["findings"][:200]:
            print(f"{f['path']}  duplicate ‘{f['heading']}’ ×{f['count']}")
        return 0 if n == 0 else 1
    _emit(rep, verdict=verdict, counts={"findings": n})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-md-dupes",
        description="Duplicate headings in *.md.")
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
