#!/usr/bin/env python3
"""kaizen-manifests CLI — multi-language manifest hygiene.

Subcommands:
  audit [--root PATH] [--json]    — list every manifest + dep counts
  unused [--root PATH] [--json]   — heuristically-unused deps
  languages [--root PATH]         — print detected languages
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _manifests as kz_m  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-manifests", tool_version="1.0.0")


def _root(args) -> Path:
    return (
        Path(args.root).expanduser().resolve()
        if getattr(args, "root", None) else Path.cwd()
    )


def _audit_json(result: dict) -> dict:
    out = dict(result)
    out["manifests"] = [
        {"language": m.language, "path": m.path,
         "deps": [dataclasses.asdict(d) for d in m.deps]}
        for m in result["manifests"]
    ]
    return out


def cmd_audit(args) -> int:
    result = kz_m.audit(_root(args))
    if args.json:
        payload = _audit_json(result)
        _emit(payload, counts={"manifests": len(payload.get("manifests", []))})
    else:
        print(kz_m.format_audit(result))
    return 0


def cmd_unused(args) -> int:
    result = kz_m.unused(_root(args))
    if args.json:
        _emit(result,
              verdict="green" if result["count"] == 0 else "yellow",
              counts={"unused": result["count"]})
    else:
        print(kz_m.format_unused(result))
    return 1 if result["count"] > 0 and args.fail_on_unused else 0


def cmd_langs(args) -> int:
    for lang in kz_m.languages_present(_root(args)):
        print(lang)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-manifests",
        description="Multi-language manifest hygiene "
                    "(Cargo + package.json + pyproject + go.mod).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("audit", help="list every manifest + dep counts")
    pa.add_argument("--root")
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_audit)

    pu = sub.add_parser("unused", help="heuristically-unused deps")
    pu.add_argument("--root")
    pu.add_argument("--fail-on-unused", action="store_true",
                    help="exit 1 when any unused dep is detected (CI gate)")
    pu.add_argument("--json", action="store_true")
    pu.set_defaults(func=cmd_unused)

    pl = sub.add_parser("languages", help="print detected languages")
    pl.add_argument("--root")
    pl.set_defaults(func=cmd_langs)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
