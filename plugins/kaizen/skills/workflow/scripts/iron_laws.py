#!/usr/bin/env python3
"""kaizen-iron-laws — CLI over the iron-laws registry.

The registry (`skills/iron-laws/domain/iron-laws.yaml`) is the single
source of truth. This CLI reads it through the iron-laws skill's
`_loader`, runs the `_iron_laws` checker, and drives `codegen`.

## Subcommands

    iron_laws.py list                       every law (id / severity / enforcement)
    iron_laws.py show <id>                  one law, full record
    iron_laws.py check [--staged|--all]     run the auto-law checks
    iron_laws.py check --law <id>           run one law's check
    iron_laws.py render                     regenerate references/iron-laws.md

No-arg invocation runs `list`. `check` exits 1 when any `hard` finding
fires (the pre-commit gate signal); 0 otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_DIR = _SCRIPT_DIR.parent.parent / "iron-laws" / "application"
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_APP_DIR))

import _iron_laws  # noqa: E402
import _loader  # noqa: E402
import codegen  # noqa: E402


def _cmd_list(_args) -> int:
    for law in _loader.load_laws():
        check = law.get("check", "—")
        print(f"{law['id']:42} {law['severity']:5} {law['enforcement']:7} {check}")
    return 0


def _cmd_show(args) -> int:
    law = _loader.get_law(args.id)
    if law is None:
        sys.stderr.write(f"iron-laws: no law with id '{args.id}'\n")
        return 1
    print(f"id:          {law['id']}")
    print(f"severity:    {law['severity']}")
    print(f"enforcement: {law['enforcement']}")
    if law.get("check"):
        print(f"check:       {law['check']}")
    print(f"statement:   {law['statement']}")
    if law.get("detect"):
        print(f"detect:      {law['detect']}")
    print(f"why:         {law['why']}")
    return 0


def _cmd_check(args) -> int:
    scope = "all" if args.all else "staged"
    findings = _iron_laws.run_checks(scope=scope, law_id=args.law)
    if not findings:
        print(f"iron-laws: 0 findings ({scope} scope)")
        return 0
    hard = sum(1 for f in findings if f.severity == "hard")
    soft = len(findings) - hard
    for f in findings:
        loc = f" [{f.path}]" if f.path else ""
        print(f"{f.severity:4} {f.law_id}: {f.message}{loc}")
        if f.detail:
            print(f"     {f.detail}")
    print(f"\niron-laws: {hard} hard, {soft} soft ({scope} scope)")
    return 1 if hard else 0


def _cmd_render(_args) -> int:
    return codegen.generate(check_only=False)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-iron-laws",
        description="CLI over the iron-laws single-source-of-truth registry.",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("list", help="list every law")
    sp_show = sub.add_parser("show", help="show one law's full record")
    sp_show.add_argument("id", help="law id")
    sp_check = sub.add_parser("check", help="run the auto-law checks")
    scope_grp = sp_check.add_mutually_exclusive_group()
    scope_grp.add_argument("--staged", action="store_true",
                           help="check the staged diff (default)")
    scope_grp.add_argument("--all", action="store_true",
                           help="audit the whole plugin")
    sp_check.add_argument("--law", help="run only this law's check")
    sub.add_parser("render", help="regenerate references/iron-laws.md")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd or "list"  # no-arg default
    return {
        "list": _cmd_list,
        "show": _cmd_show,
        "check": _cmd_check,
        "render": _cmd_render,
    }[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
