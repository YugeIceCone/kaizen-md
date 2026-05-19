#!/usr/bin/env python3
"""kaizen state — read-only JSON aggregator over kaizen's state files.

The plugin scatters JSON state across `~/.claude/.kaizen/`:

  workflow/backlog.json    workflow/state.json    session-mode.json
  gold/<slug>/mine-cursor.json    gold/<slug>/proposals.jsonl
  inbox/*.json    token-bloat-findings.json    data/handoff.db  (skipped)

`kaizen-state` walks them, classifies each by category, and emits a
unified inventory. Read-only — sources stay in place. Use this when
auditing what's persisted vs querying any single file directly.

## Subcommands

  list [--json]           one row per JSON state file (path, size, category)
  show <name>             cat the parsed JSON of one named file
  dump [--json]           single blob: {<file-name>: <parsed contents>}
  path                    print the resolved KAIZEN_DIR

Override the root: KAIZEN_DIR=<dir> kaizen state list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _kaizen_dir() -> Path:
    env = os.environ.get("KAIZEN_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen"


# Category tagging — folder-prefix → human label. First match wins.
_CATEGORIES: list[tuple[str, str]] = [
    ("workflow/",     "workflow"),
    ("gold/",         "gold"),
    ("inbox/",        "inbox"),
    ("dxm/",          "observability"),
    ("indexes/",      "index"),
    ("data/",         "data"),
    ("session-",      "session"),
    ("token-bloat",   "audit"),
]


def _classify(rel: str) -> str:
    for prefix, label in _CATEGORIES:
        if rel.startswith(prefix) or rel.startswith("./" + prefix):
            return label
        if prefix in rel:
            return label
    return "other"


def _walk_json_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip archive + backups (large, not live state)
        dirnames[:] = [d for d in dirnames
                        if d not in {"archive", "backups", ".retired"}]
        for name in filenames:
            if name.endswith(".json"):
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
        "category": _classify(rel),
    }


def _safe_load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def cmd_list(args) -> int:
    root = _kaizen_dir()
    files = _walk_json_files(root)
    records = [_file_record(p, root) for p in files]
    if args.json:
        print(json.dumps({"root": str(root), "count": len(records),
                            "files": records}, indent=2))
    else:
        print(f"kaizen state — {len(records)} JSON file(s) under {root}")
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
    root = _kaizen_dir()
    matches = [p for p in _walk_json_files(root) if p.name == args.name]
    if not matches:
        sys.stderr.write(f"[kaizen-state] no JSON file named {args.name!r} under {root}\n")
        return 1
    # First match if multiple — they get listed by `list` for disambiguation
    target = matches[0]
    data = _safe_load(target)
    if data is None:
        sys.stderr.write(f"[kaizen-state] {target} is not parseable JSON\n")
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_dump(args) -> int:
    root = _kaizen_dir()
    aggregate: dict = {}
    for p in _walk_json_files(root):
        data = _safe_load(p)
        if data is None:
            continue
        # Use bare filename as key; on collision, prepend category for clarity
        key = p.name
        if key in aggregate:
            key = f"{_classify(str(p.relative_to(root)))}/{p.name}"
        aggregate[key] = data
    if args.json:
        print(json.dumps({"root": str(root),
                            "files": list(aggregate.keys()),
                            "data": aggregate}, indent=2))
    else:
        print(json.dumps(aggregate, indent=2))
    return 0


def cmd_path(args) -> int:
    print(_kaizen_dir())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-state",
        description="Read-only JSON aggregator over kaizen state files.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="enumerate JSON state files")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("show", help="cat the parsed JSON of one named file")
    ps.add_argument("name", help="filename to look up (e.g. backlog.json)")
    ps.set_defaults(func=cmd_show)

    pd = sub.add_parser("dump", help="single blob of all parseable JSON state")
    pd.add_argument("--json", action="store_true",
                     help="wrap in {root, files, data} envelope")
    pd.set_defaults(func=cmd_dump)

    pp = sub.add_parser("path", help="print resolved KAIZEN_DIR")
    pp.set_defaults(func=cmd_path)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
