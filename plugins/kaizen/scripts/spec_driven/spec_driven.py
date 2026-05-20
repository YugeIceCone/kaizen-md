#!/usr/bin/env python3
"""kaizen-spec-driven — EARS lint + confidence score + phase gate.

Verbs:

  lint-ears <file>            walk requirements.md; report EARS violations
  score <file>                heuristic confidence score (0-100) + advisory
  gate <plan> --id <item-id>  verify phase gate (status + hash + tasks)
                              before advancing the workflow runner

All output supports --json for machine consumption.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent))
import _ears
import _gate


def cmd_lint_ears(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    result = _ears.lint_requirements(text)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0 if result["ok"] else 1
    print(f"total REQ/NFR lines: {result['total']}")
    print(f"violations:          {len(result['violations'])}")
    print(f"by pattern:          {', '.join(f'{k}={v}' for k,v in result['by_pattern'].items() if v)}")
    if result["violations"]:
        print()
        print("violations:")
        for v in result["violations"]:
            print(f"  line {v['line_num']:>4} {v['id']:8s}  {v['reason']}")
            print(f"             > {v['clause']}")
        return 1
    print("✓ all requirements EARS-compliant")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    result = _ears.score_requirements(text)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0
    print(f"score:    {result['score']:.1f} / 100")
    print(f"advisory: {result['advisory']}")
    print()
    print("signals:")
    for k, v in result["signals"].items():
        print(f"  {k:20s} {v}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    result = _gate.gate_check(
        args.plan, args.id,
        require_shipped=not args.allow_active,
        require_all_tasks_completed=args.all_tasks_completed,
    )
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return 0 if result["ok"] else 1
    if result["ok"]:
        print(f"✓ gate clear — item {args.id} status={result['item_status']}, "
              f"hash {'ok' if result['hash_ok'] else 'first-read'}")
        if result.get("task_summary"):
            ts = result["task_summary"]
            print(f"  tasks: completed={ts['completed']}/{ts['total']}")
        return 0
    print(f"✗ gate BLOCKED — {result['reason']}")
    print(f"  item_status: {result['item_status']}")
    print(f"  hash_ok:     {result['hash_ok']}")
    if result.get("task_summary"):
        ts = result["task_summary"]
        print(f"  tasks: pending={ts['pending']} in_progress={ts['in_progress']} "
              f"completed={ts['completed']} blocked={ts['blocked']} total={ts['total']}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-spec-driven",
        description="EARS lint + confidence score + phase gate for SDD",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("lint-ears",
                        help="walk requirements.md for EARS violations")
    lp.add_argument("file")
    lp.add_argument("--json", action="store_true")
    lp.set_defaults(func=cmd_lint_ears)

    sp = sub.add_parser("score",
                        help="heuristic confidence score 0-100 + advisory")
    sp.add_argument("file")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_score)

    gp = sub.add_parser("gate",
                        help="phase-gate check on a blueprint item")
    gp.add_argument("plan", help="path to plan.{json,yaml}")
    gp.add_argument("--id", required=True, help="item id to verify")
    gp.add_argument("--allow-active", action="store_true",
                    help="accept status=active (default: require shipped)")
    gp.add_argument("--all-tasks-completed", action="store_true",
                    help="for task-list items, require every task completed")
    gp.add_argument("--json", action="store_true")
    gp.set_defaults(func=cmd_gate)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
