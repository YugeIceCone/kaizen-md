#!/usr/bin/env python3
"""kaizen-mcp-coverage — every `*_mcp.py` MUST be mounted into the
FastMCP gateway via the `SUBSERVERS` list in gateway.py. Orphans (on
disk, not mounted) ship without being exposed to Claude Code.

Stdlib only. Subcommands: report | gaps.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-mcp-coverage", tool_version="1.0.0")
_SUB_RE = re.compile(r'\(\s*"[^"]+"\s*,\s*"([a-zA-Z0-9_]+)"\s*\)')


def _plugin_root() -> Path:
    return _SCRIPT_DIR.parents[2]


def _mcp_modules_on_disk(scripts_dir: Path) -> list[str]:
    return sorted(p.stem for p in scripts_dir.glob("*_mcp.py")
                  if not p.name.startswith("_"))


def _mounted_subservers(gateway_py: Path) -> set[str]:
    text = gateway_py.read_text(encoding="utf-8")
    return set(_SUB_RE.findall(text))


def scan(*, scripts_dir: Path, gateway_py: Path) -> dict:
    on_disk = _mcp_modules_on_disk(scripts_dir)
    mounted = _mounted_subservers(gateway_py)
    orphans = sorted(set(on_disk) - mounted - {"gateway"})
    missing = sorted(mounted - set(on_disk))
    return {
        "mcp_modules_on_disk": len(on_disk),
        "mounted_subservers":  len(mounted),
        "orphans":             [{"module": m} for m in orphans],
        "missing":             [{"module": m} for m in missing],
        "gaps_total":          len(orphans) + len(missing),
    }


def _run(args) -> int:
    rep = scan(scripts_dir=_plugin_root() / "skills/workflow/scripts",
                gateway_py=_plugin_root() / "skills/workflow/scripts/gateway.py")
    gaps = rep["gaps_total"]
    verdict = "green" if gaps == 0 else ("yellow" if gaps <= 3 else "red")
    if args.cmd == "gaps" and not args.json:
        for o in rep["orphans"]:
            print(f"orphan {o['module']}")
        for m in rep["missing"]:
            print(f"missing {m['module']}")
        return 0 if gaps == 0 else 1
    _emit(rep, verdict=verdict, counts={"gaps": gaps})
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaizen-mcp-coverage",
        description="Audit *_mcp.py mount coverage in gateway.py SUBSERVERS.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("report", "gaps"):
        s = sub.add_parser(n)
        s.add_argument("--json", action="store_true")
        s.set_defaults(func=_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
