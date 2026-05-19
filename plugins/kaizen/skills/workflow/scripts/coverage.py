#!/usr/bin/env python3
"""kaizen-coverage — mechanical 1:1 code-to-test mapper.

Walks `plugins/kaizen/skills/workflow/scripts/*.py` and reports
which scripts have a matching `tests/test_<x>*.py` and which don't.

Stdlib-only. The goal is the 1:1 ratio metric: every public script
should have at least one test file pointing at it.

## What counts as a 'source script'

The denominator includes every `.py` file under workflow/scripts/
EXCEPT:

- `_<x>.py` — private helpers (no public API; tested via consumers)
- `<x>_mcp.py` — MCP servers (tested via their parent feature)

## What counts as 'covered'

A source `<name>.py` is covered when ANY of these test files exists:

- `tests/test_<name>.py` (exact)
- `tests/test_<name>_*.py` (variants — e.g. test_build_index_search.py covers build_index.py)
- `tests/test_<head>*.py` where head = <name>.split('_')[0]
  (so brain_audit.py is covered by test_brain.py — parent feature tests
  exercise the op script indirectly via integration)

## CLI

    coverage.py summary [--json]   one-line ratio + count
    coverage.py gaps [--json]      only uncovered scripts (exit 1 if any)
    coverage.py report [--json]    full per-script breakdown

    --root <dir>    override plugin root (default: auto-discover from script location)

## Exit codes

- 0   summary/report always; gaps when all covered
- 1   gaps when there are uncovered scripts (for CI gating)
- 2   bad arguments / unreadable root
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _default_root() -> Path:
    """Auto-discover plugins/kaizen root from this script's location."""
    return Path(__file__).resolve().parents[3]


def _list_source_scripts(root: Path) -> list[str]:
    """Public script stems under skills/workflow/scripts/ (sorted)."""
    scripts = root / "skills" / "workflow" / "scripts"
    out: list[str] = []
    for p in sorted(scripts.glob("*.py")):
        stem = p.stem
        if stem.startswith("_"):
            continue  # private helper
        if stem.endswith("_mcp"):
            continue  # MCP server
        out.append(stem)
    return out


def _test_stems(root: Path) -> set[str]:
    """test_<x>.py → 'x' for every test file."""
    tests = root / "tests"
    if not tests.is_dir():
        return set()
    out: set[str] = set()
    for p in tests.glob("test_*.py"):
        out.add(p.stem[len("test_"):])
    return out


def _is_covered(script_stem: str, test_stems: set[str]) -> bool:
    """A script is covered when any test name matches by stem, op-suffix
    expansion, or parent-feature head."""
    # 1) Exact match
    if script_stem in test_stems:
        return True
    # 2) <script>_<op> matches test_<script>_* or test_<script>
    head = script_stem.split("_")[0]
    for t in test_stems:
        if t == script_stem:
            return True
        if t.startswith(script_stem + "_"):
            return True
        if script_stem.startswith(t + "_"):
            return True
        # 3) Parent-feature: brain_audit covered by test_brain*
        if t == head or t.startswith(head + "_"):
            return True
    return False


def _compute(root: Path) -> dict:
    """Build the coverage dict — used by all subcommands."""
    srcs = _list_source_scripts(root)
    tests = _test_stems(root)
    rows = []
    covered_count = 0
    uncovered: list[str] = []
    for s in srcs:
        cov = _is_covered(s, tests)
        rows.append({"script": s, "covered": cov})
        if cov:
            covered_count += 1
        else:
            uncovered.append(s)
    total = len(srcs)
    ratio = (100 * covered_count // total) if total else 0
    return {
        "total":      total,
        "covered":    covered_count,
        "ratio_pct":  ratio,
        "uncovered":  uncovered,
        "scripts":    rows,
    }


def _print_summary(data: dict, as_json: bool) -> None:
    if as_json:
        # Trim scripts[] from summary — that belongs in report.
        out = {k: v for k, v in data.items() if k != "scripts"}
        print(json.dumps(out))
    else:
        print(f"kaizen-coverage: {data['covered']}/{data['total']} scripts "
              f"({data['ratio_pct']}%); {len(data['uncovered'])} uncovered")


def _print_gaps(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"uncovered": data["uncovered"]}))
    else:
        for s in data["uncovered"]:
            print(s)


def _print_report(data: dict, as_json: bool) -> None:
    if as_json:
        # Reshape for the report — summary block + per-script rows.
        out = {
            "summary": {
                "total":             data["total"],
                "covered":           data["covered"],
                "uncovered_count":   len(data["uncovered"]),
                "ratio_pct":         data["ratio_pct"],
            },
            "scripts": data["scripts"],
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"kaizen-coverage report ({data['ratio_pct']}% — "
              f"{data['covered']}/{data['total']} covered)")
        for row in data["scripts"]:
            mark = "✓" if row["covered"] else "✗"
            print(f"  {mark} {row['script']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kaizen-coverage",
                                  description="1:1 code-to-test mapper")
    p.add_argument("--root", type=Path, default=None,
                    help="plugin root (default: auto-discover)")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, helptext in (
        ("summary", "one-line ratio + count"),
        ("gaps",    "list uncovered scripts (exit 1 if any)"),
        ("report",  "full per-script breakdown"),
    ):
        ps = sub.add_parser(name, help=helptext)
        ps.add_argument("--json", action="store_true",
                         help="emit JSON instead of text")

    args = p.parse_args(argv)
    root = args.root or _default_root()
    if not root.is_dir():
        sys.stderr.write(f"[kaizen-coverage] root not found: {root}\n")
        return 2

    data = _compute(root)

    if args.cmd == "summary":
        _print_summary(data, args.json)
        return 0
    if args.cmd == "gaps":
        _print_gaps(data, args.json)
        return 1 if data["uncovered"] else 0
    if args.cmd == "report":
        _print_report(data, args.json)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
