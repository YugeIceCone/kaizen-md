#!/usr/bin/env python3
"""kaizen-slash-collision — surface tab-completion-ambiguous slash pairs.

When 2+ `/kaizen:<slash>` commands share a >=N-char prefix (default 4),
tab-completion + skill-suggest routing get ambiguous. Lint catches the
collisions before they ship — caller can either rename one slash or
accept the collision as intentional (e.g. trace / trace-search /
trace-proxy is an explicit family).

Stdlib-only. Mirrors the existing axis pattern (token-bloat / coverage /
schema-coverage / name-quality / frontmatter).

## CLI

  python3 slash_collision.py check [--dir <commands-dir>] [--min N] [--json]

Exit 0 = no collisions; exit 1 = at least one collision group found.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_DEFAULT_MIN_PREFIX = 4

def find_collisions(names: list[str], min_prefix_len: int = _DEFAULT_MIN_PREFIX
                     ) -> list[dict]:
    """Pure-function detector: group `names` by their first
    `min_prefix_len` chars; return one dict per group with ≥2 members.

    Each finding: ``{"prefix": "<chars>", "members": ["a", "b", ...]}``.
    Names shorter than `min_prefix_len` are skipped (can't collide at
    that depth). Sorted by prefix for deterministic output.
    """
    if min_prefix_len < 1:
        raise ValueError("min_prefix_len must be >= 1")
    buckets: dict[str, list[str]] = defaultdict(list)
    for name in names:
        if len(name) < min_prefix_len:
            continue
        buckets[name[:min_prefix_len]].append(name)
    out = []
    for prefix in sorted(buckets):
        members = buckets[prefix]
        if len(members) >= 2:
            out.append({"prefix": prefix, "members": sorted(members)})
    return out

def scan_commands_dir(commands_dir: Path,
                       min_prefix_len: int = _DEFAULT_MIN_PREFIX
                       ) -> list[dict]:
    """Scan `commands_dir` for `*.md` slashes, run collision detection."""
    if not commands_dir.is_dir():
        return []
    names = sorted(p.stem for p in commands_dir.iterdir() if p.suffix == ".md")
    return find_collisions(names, min_prefix_len=min_prefix_len)

def _plugin_commands_dir() -> Path:
    """Default scan target: the kaizen plugin's commands/ dir.

    Post-DOMAIN-5 (scripts/quality/X.py depth): parents[2] = plugin root.
    """
    return Path(__file__).resolve().parents[2] / "commands"

def _cmd_check(args) -> int:
    target = Path(args.dir) if args.dir else _plugin_commands_dir()
    collisions = scan_commands_dir(target, min_prefix_len=args.min)
    if args.json:
        print(json.dumps({
            "scan_dir":    str(target),
            "min_prefix":  args.min,
            "collisions":  collisions,
            "count":       len(collisions),
        }, indent=2))
    else:
        if not collisions:
            print(f"slash-collision: no collisions (≥{args.min}-char "
                  f"prefix) in {target}")
        else:
            print(f"slash-collision: {len(collisions)} group(s) — "
                  f"≥{args.min}-char prefix in {target}")
            for c in collisions:
                print(f"  ⚠ '{c['prefix']}*' — {', '.join(c['members'])}")
    return 1 if collisions else 0

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-slash-collision",
        description="Detect tab-completion-ambiguous slash pairs in commands/",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="run collision check; exit 1 on findings")
    c.add_argument("--dir", default=None,
                    help="commands dir to scan (default: plugin commands/)")
    c.add_argument("--min", type=int, default=_DEFAULT_MIN_PREFIX,
                    help=f"min prefix length to flag (default {_DEFAULT_MIN_PREFIX})")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=_cmd_check)

    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
