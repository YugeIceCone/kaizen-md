#!/usr/bin/env python3
"""kaizen-inventory — walk a plugin tree, dump file contents to a bundle.

Stdlib-only. Recursive walk with type + glob filtering. Designed for
feeding agents / grep / external review. Three output formats:

  markdown  one section per file with path header + fenced content
  jsonl     one record per file: {path, type, bytes, lines, content}
  raw       file contents separated by `>>> <path>` markers

## CLI

  kaizen-inventory dump   [--type py,yaml,json,jsonl,schema.json,md,sh]
                          [--include GLOB] [--exclude GLOB]
                          [--root PATH] [--out FILE]
                          [--format markdown|jsonl|raw]
                          [--max-size BYTES]
  kaizen-inventory list   [--type ...] [--include ...] [--exclude ...]
                          [--root ...] [--json]
  kaizen-inventory stats  [--root PATH]

## Defaults

  --root      plugins/kaizen/ (auto-detected from cwd; --root . for whole repo)
  --type      py, yaml, yml, json, jsonl, md, sh, schema.json (all canonical)
  --format    markdown
  --max-size  200000 (200KB; skips bigger files with a stub)
  --exclude   __pycache__/, .git/, *.pyc, *.pyo, node_modules/ — always
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

# ─── Defaults ─────────────────────────────────────────────────────

CANONICAL_TYPES = ["py", "yaml", "yml", "json", "jsonl", "md", "sh", "schema.json"]
ALWAYS_EXCLUDE = ["*/__pycache__/*", "*/.git/*", "*.pyc", "*.pyo",
                  "*/node_modules/*", "*/.venv/*", "*/venv/*"]
MAX_SIZE_DEFAULT = 200_000

EXT_TO_LANG = {
    "py": "python", "yaml": "yaml", "yml": "yaml", "json": "json",
    "jsonl": "json", "md": "markdown", "sh": "bash",
    "schema.json": "json",
}

# ─── Core walk ────────────────────────────────────────────────────

def file_type(p: Path) -> str | None:
    """Return the canonical type label for p, or None if it doesn't match."""
    name = p.name
    if name.endswith(".schema.json"):
        return "schema.json"
    suf = p.suffix.lstrip(".")
    return suf if suf in CANONICAL_TYPES else None


def matches_any(path_str: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path_str, pat) for pat in patterns)


def iter_files(root: Path, types: list[str],
               include: list[str], exclude: list[str]) -> list[Path]:
    """Yield every file under root matching the type + glob filters."""
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root.parent if root.parent != Path() else root))
        if matches_any(rel, ALWAYS_EXCLUDE):
            continue
        t = file_type(p)
        if t is None or t not in types:
            continue
        if include and not matches_any(rel, include):
            continue
        if exclude and matches_any(rel, exclude):
            continue
        out.append(p)
    return out


def read_safe(p: Path, max_size: int) -> tuple[str, bool]:
    """Read file content; return (content, truncated_flag)."""
    try:
        size = p.stat().st_size
        if size > max_size:
            return (f"[skipped — {size} bytes > {max_size} max]", True)
        return (p.read_text(encoding="utf-8", errors="replace"), False)
    except OSError as e:
        return (f"[read error: {e}]", True)

# ─── Output emitters ──────────────────────────────────────────────

def emit_markdown(files: list[Path], root: Path, max_size: int,
                  out) -> None:
    for p in files:
        rel = p.relative_to(root.parent if root.name == "kaizen" else root)
        t = file_type(p) or "txt"
        lang = EXT_TO_LANG.get(t, "")
        content, _ = read_safe(p, max_size)
        out.write(f"\n## `{rel}`\n\n")
        out.write(f"```{lang}\n{content}\n```\n")


def emit_jsonl(files: list[Path], root: Path, max_size: int,
               out) -> None:
    for p in files:
        rel = str(p.relative_to(root.parent if root.name == "kaizen" else root))
        content, truncated = read_safe(p, max_size)
        rec = {
            "path": rel,
            "type": file_type(p),
            "bytes": p.stat().st_size,
            "lines": content.count("\n") + 1,
            "truncated": truncated,
            "content": content,
        }
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")


def emit_raw(files: list[Path], root: Path, max_size: int, out) -> None:
    for p in files:
        rel = p.relative_to(root.parent if root.name == "kaizen" else root)
        content, _ = read_safe(p, max_size)
        out.write(f"\n>>> {rel}\n")
        out.write(content)
        if not content.endswith("\n"):
            out.write("\n")

# ─── Subcommands ──────────────────────────────────────────────────

def cmd_dump(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    types = args.type or CANONICAL_TYPES
    files = iter_files(root, types, args.include, args.exclude)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1

    out_stream = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        if args.format == "markdown":
            out_stream.write(f"# inventory dump — {root}\n")
            out_stream.write(f"\n{len(files)} files matched. "
                              f"Types: {','.join(types)}. Max size: {args.max_size}.\n")
            emit_markdown(files, root, args.max_size, out_stream)
        elif args.format == "jsonl":
            emit_jsonl(files, root, args.max_size, out_stream)
        elif args.format == "raw":
            emit_raw(files, root, args.max_size, out_stream)
    finally:
        if args.out:
            out_stream.close()
            print(f"wrote {len(files)} files to {args.out}", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    types = args.type or CANONICAL_TYPES
    files = iter_files(root, types, args.include, args.exclude)
    if args.json:
        rows = []
        for p in files:
            rel = str(p.relative_to(root.parent if root.name == "kaizen" else root))
            rows.append({"path": rel, "type": file_type(p), "bytes": p.stat().st_size})
        print(json.dumps(rows, indent=2))
    else:
        for p in files:
            rel = p.relative_to(root.parent if root.name == "kaizen" else root)
            print(rel)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    types = CANONICAL_TYPES
    files = iter_files(root, types, [], [])
    by_type: dict[str, dict[str, int]] = {}
    for p in files:
        t = file_type(p) or "?"
        slot = by_type.setdefault(t, {"count": 0, "bytes": 0})
        slot["count"] += 1
        slot["bytes"] += p.stat().st_size
    print(f"inventory stats — {root}")
    print(f"  total: {sum(s['count'] for s in by_type.values())} files, "
          f"{sum(s['bytes'] for s in by_type.values())} bytes")
    for t in sorted(by_type, key=lambda x: -by_type[x]["count"]):
        s = by_type[t]
        print(f"  {t:14s} {s['count']:6d} files  {s['bytes']:>10d} bytes")
    return 0

# ─── CLI ──────────────────────────────────────────────────────────

def _detect_root() -> Path:
    """Pick a sensible default root: plugins/kaizen/ if present, else cwd."""
    cwd = Path.cwd()
    for cand in [cwd / "plugins" / "kaizen", cwd]:
        if cand.is_dir():
            return cand
    return cwd


def _add_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--type", action="append", choices=CANONICAL_TYPES,
                    help="file type to include (repeatable; default = all canonical)")
    p.add_argument("--include", action="append", default=[],
                    metavar="GLOB", help="restrict to paths matching glob (repeatable)")
    p.add_argument("--exclude", action="append", default=[],
                    metavar="GLOB", help="skip paths matching glob (repeatable)")
    p.add_argument("--root", type=Path, default=_detect_root(),
                    help="walk root (default: plugins/kaizen/ if present, else cwd)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kaizen-inventory",
        description="Walk a plugin tree; dump file contents to a bundle.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="emit file contents with path headers")
    _add_filter_args(p_dump)
    p_dump.add_argument("--out", metavar="FILE",
                        help="write to FILE (default: stdout)")
    p_dump.add_argument("--format", choices=["markdown", "jsonl", "raw"],
                        default="markdown")
    p_dump.add_argument("--max-size", type=int, default=MAX_SIZE_DEFAULT,
                        help=f"skip files larger than this many bytes (default {MAX_SIZE_DEFAULT})")
    p_dump.set_defaults(func=cmd_dump)

    p_list = sub.add_parser("list", help="list matching paths (no content)")
    _add_filter_args(p_list)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_stats = sub.add_parser("stats", help="per-type counts + bytes")
    p_stats.add_argument("--root", type=Path, default=_detect_root())
    p_stats.set_defaults(func=cmd_stats)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
