"""kaizen-plugin-docs — utility surface tracker for plugins/kaizen/ docs.

Symmetry with kaizen-bundle but for DURABLE docs (no bundle/session
concept; no mutation). Walks the canonical doc surfaces of the kaizen
plugin: skills (SKILL.md), skill references, commands, agents, root
docs, and domain configs. Reports counts + per-file metadata + content-
hash dupes.

  kaizen-plugin-docs scan [--json]
                   # walk + report counts + dupes
  kaizen-plugin-docs list [--kind <kind>] [--json]
                   # listing with per-file metadata

Kinds (kind classifier — pure function over a path):
  skill          plugins/kaizen/skills/<name>/SKILL.md
  reference      plugins/kaizen/skills/<name>/references/*.md
  command        plugins/kaizen/commands/*.md
  agent          plugins/kaizen/agents/*.md
  root           plugins/kaizen/{README,CLAUDE,CHANGELOG,ATTRIBUTIONS,
                  CONTRIBUTING}.md
  domain         plugins/kaizen/skills/<name>/domain/**.{yaml,json}
  None           (file not in the doc surface)

Design contract (per registry 2026-05-18):
  PROGRAMMABLE  — classify_kind, scan_root, sha_of are pure callables
  REPRODUCIBLE  — same disk state → same scan output
  CONSISTENT    — env-overridable root via KAIZEN_PLUGIN_ROOT;
                  --json everywhere; exit 0 on success
  DETERMINISTIC — no time-of-day branching; no randomness
  REUSABLE     — kind registry is one frozenset; adding new doc
                  categories is a one-line change
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

_ROOT_DOCS = frozenset({
    "README.md", "CLAUDE.md", "CHANGELOG.md",
    "ATTRIBUTIONS.md", "CONTRIBUTING.md",
})

# Umbrella subcommands — consolidated-CLI-parent pattern. Each maps to
# an existing sibling bin (still callable directly for back-compat).
# Per user 2026-05-18 "consolidate docs related systems/logic under
# this new one."
UMBRELLA_BINS: dict[str, str] = {
    "frontmatter":    "kaizen-frontmatter",
    "links":          "kaizen-md-link-rot",
    "dupes":          "kaizen-md-dupes",
    "whitespace":     "kaizen-md-whitespace",
    "heading-depth":  "kaizen-md-heading-depth",
}

def resolve_umbrella_bin(subcommand: str) -> str | None:
    """Pure compute — return the sibling bin name for an umbrella
    subcommand, or None if unknown."""
    return UMBRELLA_BINS.get(subcommand)

def _plugin_root() -> Path:
    env = os.environ.get("KAIZEN_PLUGIN_ROOT")
    if env:
        return Path(env)
    # Default — resolve via the script's location.
    return Path(__file__).resolve().parent.parent.parent.parent

def classify_kind(path: Path) -> Optional[str]:
    """Pure-function kind classifier — None if path is not in the doc surface."""
    s = str(path).replace("\\", "/")
    if s.endswith("/SKILL.md") and "/skills/" in s:
        return "skill"
    if re.search(r"/skills/[^/]+/references/[^/]+\.md$", s):
        return "reference"
    if re.search(r"/schemas/[^/]+/", s) and (
        s.endswith(".yaml") or s.endswith(".json")
    ):
        return "domain"
    if re.search(r"/commands/[^/]+\.md$", s):
        return "command"
    if re.search(r"/agents/[^/]+\.md$", s):
        return "agent"
    if path.name in _ROOT_DOCS:
        return "root"
    return None

def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""

def scan_root(root: Path) -> list[dict]:
    """Walk `root` and return per-file metadata for every doc-surface file.

    Entry: {path: str (relative-to-root), kind: str, size: int, sha256: str}.
    """
    if not root.is_dir():
        return []
    out: list[dict] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        kind = classify_kind(p)
        if kind is None:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        out.append({
            "path": str(p.relative_to(root)),
            "kind": kind,
            "size": size,
            "sha256": _sha256_file(p),
        })
    return sorted(out, key=lambda e: e["path"])

def _compute_dupes(entries: list[dict]) -> list[dict]:
    """Group entries by sha256; return groups with ≥2 members."""
    by_sha: dict[str, list[str]] = {}
    for e in entries:
        if e["sha256"]:
            by_sha.setdefault(e["sha256"], []).append(e["path"])
    return [
        {"sha256": sha, "paths": paths}
        for sha, paths in by_sha.items() if len(paths) >= 2
    ]

def _cmd_scan(args) -> int:
    root = _plugin_root()
    entries = scan_root(root)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    dupes = _compute_dupes(entries)
    result = {
        "root": str(root),
        "total": len(entries),
        "counts": counts,
        "dupes": dupes,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"root: {root}")
        print(f"total: {result['total']}")
        for kind in sorted(counts):
            print(f"  {kind}: {counts[kind]}")
        if dupes:
            print(f"dupes (identical content): {len(dupes)}")
            for d in dupes:
                print(f"  sha={d['sha256'][:12]}  paths={d['paths']}")
    return 0

def _cmd_list(args) -> int:
    root = _plugin_root()
    entries = scan_root(root)
    if args.kind:
        entries = [e for e in entries if e["kind"] == args.kind]
    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        for e in entries:
            print(f"{e['kind']:<10}  {e['size']:>7}B  {e['path']}")
    return 0

def _cmd_umbrella(args, subcommand: str) -> int:
    """Dispatch an umbrella subcommand to its sibling bin. Passes raw
    args through (subparser uses parse_known_args via REMAINDER)."""
    import subprocess
    bin_name = resolve_umbrella_bin(subcommand)
    if bin_name is None:
        sys.stderr.write(f"kaizen-plugin-docs: unknown umbrella: {subcommand}\n")
        return 1
    bin_path = Path(__file__).resolve().parent.parent.parent.parent / "bin" / bin_name
    if not bin_path.is_file():
        sys.stderr.write(f"kaizen-plugin-docs: bin not found: {bin_path}\n")
        return 1
    rest = getattr(args, "rest", []) or []
    return subprocess.run(["bash", str(bin_path), *rest]).returncode

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-plugin-docs",
        description="Utility surface tracker for plugins/kaizen/ docs. "
                    "Native subcommands (scan/list) + umbrella dispatchers "
                    "to sibling docs bins (frontmatter/links/dupes/whitespace/"
                    "heading-depth).",
    )
    sub = p.add_subparsers(dest="command")

    ps = sub.add_parser("scan", help="counts per kind + dupe detection")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(fn=_cmd_scan)

    pl = sub.add_parser("list", help="per-file listing")
    pl.add_argument("--kind", default=None,
                     choices=["skill", "reference", "command", "agent",
                              "root", "domain"],
                     help="filter by kind")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=_cmd_list)

    # Umbrella subcommands — dispatch to sibling bins.
    for subname, bin_name in UMBRELLA_BINS.items():
        u = sub.add_parser(
            subname,
            help=f"→ {bin_name} (umbrella dispatcher; passes args through)",
        )
        u.add_argument("rest", nargs=argparse.REMAINDER,
                        help="args forwarded to the underlying bin")
        u.set_defaults(fn=lambda a, _s=subname: _cmd_umbrella(a, _s))

    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help()
        return 2
    return args.fn(args)

if __name__ == "__main__":
    sys.exit(main())
