"""GC dangling `kaizen-*` symlinks from the user bin directory.

`/kaizen:setup` symlinks every `<plugin>/bin/kaizen-*` into `~/.local/bin/`.
When a plugin update renames or deletes a source bin, the symlink in
the user-bin is left dangling. This helper reaps those orphans before
setup.sh re-links, keeping the user-bin clean across versions.

Usage:
    prune_bin_symlinks.py --user-bin <path> [--dry-run] [--json]

Removes any symlink under --user-bin whose name begins with `kaizen`
AND whose target does not exist. Non-symlinks, non-kaizen names, and
live symlinks are left untouched.

Idempotent. Exit 0 always (advisory cleanup).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

def prune_orphans(user_bin: Path, *, dry_run: bool = False) -> list[str]:
    if not user_bin.is_dir():
        return []
    removed: list[str] = []
    for entry in sorted(user_bin.iterdir()):
        if not entry.name.startswith("kaizen"):
            continue
        if not entry.is_symlink():
            continue
        if os.path.exists(entry):  # follows the symlink; True iff target exists
            continue
        if not dry_run:
            entry.unlink()
        removed.append(entry.name)
    return removed

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--user-bin", required=True, type=Path,
                   help="directory to scan (typically ~/.local/bin)")
    p.add_argument("--dry-run", action="store_true",
                   help="report orphans without removing")
    p.add_argument("--json", action="store_true",
                   help="emit a JSON payload instead of human prose")
    args = p.parse_args(argv)

    removed = prune_orphans(args.user_bin, dry_run=args.dry_run)

    if args.json:
        print(json.dumps({
            "removed": removed,
            "count": len(removed),
            "dry_run": bool(args.dry_run),
            "user_bin": str(args.user_bin),
        }))
    else:
        if removed:
            verb = "would remove" if args.dry_run else "removed"
            print(f"{verb} {len(removed)} orphan kaizen-* symlink(s):")
            for name in removed:
                print(f"  - {name}")
        else:
            print("no orphan kaizen-* symlinks found")
    return 0

if __name__ == "__main__":
    sys.exit(main())
