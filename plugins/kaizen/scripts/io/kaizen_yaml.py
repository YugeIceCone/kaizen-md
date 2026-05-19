#!/usr/bin/env python3
"""kaizen yaml — read-only YAML aggregator over plugin configs.

Walks the plugin tree + handoff store, classifies each YAML by what
it encodes (rubric / config / rule-catalog / workflow-routine / handoff),
and exposes list / show / lint over the lot.

## Subcommands

  list [--json]           one row per YAML file (path, size, category)
  show <name>             cat the parsed YAML of one named file (as JSON)
  lint                    PyYAML-parse every file; exit 1 on any failure
  path                    print the resolved plugin root

Override the plugin root: KAIZEN_PLUGIN_ROOT=<dir> kaizen yaml list

## Why yaml-only

YAML is the kaizen project's chosen format for human-editable
configuration (rubrics, schemas, intents, iron-laws, routines,
handoffs). This CLI gives a single view across the scattered files;
sources stay in place. SoC: state.py owns JSON state files, this CLI
owns YAML configs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _plugin_root() -> Path:
    env = os.environ.get("KAIZEN_PLUGIN_ROOT")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    # Sibling-walk: this script lives at scripts/io/, so
    # plugin root is two parents up.
    here = Path(__file__).resolve().parent
    return here.parent.parent


# Category classifier — folder/filename → human label. First match wins.
def _classify(rel: str, name: str) -> str:
    if name.endswith("-rubric.yaml") or name == "rubric.yaml":
        return "rubric"
    if name in ("intents.yaml", "intent.yaml") or "intents" in rel:
        return "rules"
    if name in ("iron-laws.yaml", "iron_laws.yaml"):
        return "rules"
    if name == "config.yaml":
        return "config"
    if name == "schema.yaml" and ("schemas/" in rel or rel.startswith("schemas")):
        return "routine"
    if name == "feature-shape.yaml" or name == "wiring-checklist.yaml":
        return "manifest"
    if "/handoff/" in rel or rel.startswith("handoff/"):
        return "handoff"
    if "domain/" in rel:
        return "config"
    return "other"


# Scan dirs — under plugin root unless absolute. Skips noise (vendored
# dependencies, tests, archives).
_SKIP_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", "archive", ".retired",
    "vendor", "tests",  # test fixtures aren't config
}


def _walk_yaml_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".yaml") or name.endswith(".yml"):
                out.append(Path(dirpath) / name)
    return sorted(out)


def _file_record(p: Path, root: Path) -> dict:
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    rel = str(p.relative_to(root))
    return {
        "name":     p.name,
        "path":     str(p),
        "relpath":  rel,
        "size":     size,
        "category": _classify(rel, p.name),
    }


def _safe_load(p: Path):
    """Best-effort PyYAML load. Returns None on parse error."""
    try:
        import yaml
    except ImportError:
        sys.stderr.write("[kaizen-yaml] PyYAML required\n")
        sys.exit(2)
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def cmd_list(args) -> int:
    root = _plugin_root()
    files = _walk_yaml_files(root)
    records = [_file_record(p, root) for p in files]
    if args.json:
        print(json.dumps({"root": str(root), "count": len(records),
                            "files": records}, indent=2))
    else:
        print(f"kaizen yaml — {len(records)} YAML file(s) under {root}")
        if not records:
            return 0
        by_cat: dict[str, list] = {}
        for r in records:
            by_cat.setdefault(r["category"], []).append(r)
        for cat, items in sorted(by_cat.items()):
            print(f"\n  [{cat}] ({len(items)}):")
            for r in items:
                print(f"    {r['size']:>8}  {r['relpath']}")
    return 0


def cmd_show(args) -> int:
    root = _plugin_root()
    matches = [p for p in _walk_yaml_files(root) if p.name == args.name]
    if not matches:
        sys.stderr.write(f"[kaizen-yaml] no YAML file named {args.name!r} under {root}\n")
        return 1
    target = matches[0]
    data = _safe_load(target)
    if data is None:
        sys.stderr.write(f"[kaizen-yaml] {target} is not parseable YAML\n")
        return 1
    print(json.dumps(data, indent=2, default=str))
    return 0


def cmd_lint(args) -> int:
    root = _plugin_root()
    files = _walk_yaml_files(root)
    pass_count = 0
    fail = []
    for p in files:
        if _safe_load(p) is None:
            fail.append(p)
        else:
            pass_count += 1
    print(f"kaizen yaml lint — {pass_count} pass, {len(fail)} fail (of {len(files)})")
    if fail:
        print("\nFailures:")
        for p in fail:
            print(f"  ✗ {p.relative_to(root)}")
        return 1
    # Print one OK marker per file (KISS — caller can grep)
    if pass_count and not args.quiet:
        for p in files:
            print(f"  ✓ {p.relative_to(root)}")
    return 0


def cmd_path(args) -> int:
    print(_plugin_root())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-yaml",
        description="Read-only YAML aggregator over plugin configs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="enumerate YAML files")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("show", help="cat the parsed YAML of one named file")
    ps.add_argument("name", help="filename to look up (e.g. dispatch-rubric.yaml)")
    ps.set_defaults(func=cmd_show)

    plt = sub.add_parser("lint", help="PyYAML-parse every file; exit 1 on failure")
    plt.add_argument("--quiet", action="store_true",
                      help="suppress per-file OK lines")
    plt.set_defaults(func=cmd_lint)

    pp = sub.add_parser("path", help="print resolved KAIZEN_PLUGIN_ROOT")
    pp.set_defaults(func=cmd_path)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
