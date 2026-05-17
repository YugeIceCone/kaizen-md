#!/usr/bin/env python3
# consolidated-cli-parent: drift
"""kaizen-drift CLI — record / check / explain.

Wraps `_drift.py`. Same paths as the MCP server: baseline at
`<root>/.kaizen/workflow/drift-baseline/`, current at `<root>/docs/crates/`.

## Subcommands

  record [--root PATH]
      Seed the baseline by copying every <root>/docs/crates/*.json
      into the baseline dir. Run once after a stable checkpoint.

  check [--root PATH] [--only UNIT] [--fail-on-drift] [--json]
      Compare baseline ↔ current. Exit 0 by default; with --fail-on-drift,
      exit 1 when any drift is detected (CI-gateable).

  explain UNIT [--root PATH]
      Detail one unit's drift (added/removed/changed items + deps + LOC).

  paths [--root PATH]
      Print the resolved baseline + current dirs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _drift as kz_drift  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-drift", tool_version="1.0.0")


def _root(args) -> Path:
    return (
        Path(args.root).expanduser().resolve()
        if getattr(args, "root", None) else Path.cwd()
    )


def cmd_record(args) -> int:
    root = _root(args)
    try:
        result = kz_drift.record_baseline(
            kz_drift.default_current_dir(root),
            kz_drift.default_baseline_dir(root),
        )
    except FileNotFoundError as e:
        sys.stderr.write(f"kaizen-drift: {e}\n")
        return 1
    print(f"recorded {result['copied']} profile(s) → {result['baseline_dir']}")
    return 0


def cmd_check(args) -> int:
    root = _root(args)
    baseline = kz_drift.default_baseline_dir(root)
    if not baseline.is_dir():
        sys.stderr.write(
            f"kaizen-drift: no baseline at {baseline}\n"
            "  run `kaizen-drift record` first\n"
        )
        return 2
    report = kz_drift.run_check(
        baseline,
        kz_drift.default_current_dir(root),
        only=args.only,
    )
    if args.json:
        import dataclasses
        payload = {
            "baseline_dir": report.baseline_dir,
            "current_dir": report.current_dir,
            "changed": [dataclasses.asdict(u) for u in report.changed],
            "added_units": report.added_units,
            "removed_units": report.removed_units,
            "total": report.total,
        }
        _emit(payload,
              verdict="green" if report.total == 0 else "yellow",
              counts={"drifted": report.total,
                      "added": len(report.added_units),
                      "removed": len(report.removed_units)})
    else:
        print(kz_drift.format_report(report))
    if args.fail_on_drift and report.total > 0:
        return 1
    return 0


def cmd_explain(args) -> int:
    root = _root(args)
    report = kz_drift.run_check(
        kz_drift.default_baseline_dir(root),
        kz_drift.default_current_dir(root),
        only=args.unit,
    )
    if args.unit in report.added_units:
        print(f"{args.unit}: NEW (not in baseline)")
        return 0
    if args.unit in report.removed_units:
        print(f"{args.unit}: REMOVED (gone from current)")
        return 0
    match = next((u for u in report.changed if u.unit == args.unit), None)
    if match is None:
        print(f"{args.unit}: unchanged (no drift)")
        return 0
    import dataclasses
    print(json.dumps(dataclasses.asdict(match), indent=2))
    return 0


def cmd_paths(args) -> int:
    root = _root(args)
    print(f"root:     {root}")
    print(f"baseline: {kz_drift.default_baseline_dir(root)}")
    print(f"current:  {kz_drift.default_current_dir(root)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-drift",
        description="Structural-drift detector — baseline vs current "
                    "JSON-profile diff.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("record", help="seed baseline from current profiles")
    pr.add_argument("--root", help="repo root (default: cwd)")
    pr.set_defaults(func=cmd_record)

    pc = sub.add_parser("check", help="diff baseline ↔ current")
    pc.add_argument("--root")
    pc.add_argument("--only", help="restrict to one unit (stem)")
    pc.add_argument("--fail-on-drift", action="store_true",
                    help="exit 1 when any drift detected (CI gate)")
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_check)

    pe = sub.add_parser("explain", help="detail one unit's drift")
    pe.add_argument("unit", help="unit stem, e.g. 'core' or 'shodan-cli'")
    pe.add_argument("--root")
    pe.set_defaults(func=cmd_explain)

    pp = sub.add_parser("paths", help="print baseline + current paths")
    pp.add_argument("--root")
    pp.set_defaults(func=cmd_paths)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
