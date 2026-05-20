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

CANONICAL_TYPES = [
    # code
    "py", "sh", "bash", "js", "cjs", "mjs", "ts", "tsx", "rs", "go", "rb",
    # markup / docs
    "md", "rst", "html", "css",
    # data / config
    "yaml", "yml", "json", "jsonl", "ndjson", "toml", "ini", "cfg", "conf",
    "env", "xml", "csv", "tsv", "dot",
    # JSON Schemas (double-extension)
    "schema.json",
    # no-extension canonical filenames (handled via _BARENAMES below)
    "LICENSE", "README", "CHANGELOG", "CONTRIBUTING", "Dockerfile",
    "Makefile", ".gitignore", ".mcp.json",
]

# Bare-name files (no extension) — match by exact basename
_BARENAMES = {"LICENSE", "README", "CHANGELOG", "CONTRIBUTING",
              "Dockerfile", "Makefile", ".gitignore", ".mcp.json"}

# Path-pattern → semantic type label. Matched FIRST (more specific than
# extension); first match wins. Patterns are fnmatch.fnmatchcase against
# the relative path from the walk-root parent. Designed for the kaizen
# plugin shape — agents reading the inventory want to filter by ROLE
# (skill / command / mcp / hook / test), not just extension.
PATH_PATTERNS: list[tuple[str, str]] = [
    # ── Agent-orientation handles (top of file; most specific shapes) ──
    ("CLAUDE.md",                                 "claude-md"),
    ("*/CLAUDE.md",                               "claude-md"),
    ("*/AGENTS.md",                               "agents-md"),
    ("*/MEMORY.md",                               "memory-index"),

    # ── SKILL.md (canonical skill location first; fallback for others) ──
    ("*/skills/*/SKILL.md",                       "skill"),
    ("*/SKILL.md",                                "skill"),

    # ── Slash commands + subagents ──
    ("*/commands/*.md",                           "command"),
    ("*/commands/*/*.md",                         "command"),
    ("*/agents/*.md",                             "agent"),

    # ── Hooks + handlers + indexers (script-cluster shapes) ──
    ("*/hooks/claude/*.sh",                       "hook-sh"),
    ("*/hooks/claude/*.py",                       "hook-py"),
    ("*/hooks/hooks.json",                        "hook-registry"),
    ("*/scripts/mcp/*_mcp.py",                    "mcp"),
    ("*/scripts/indexers/*.py",                   "indexer"),
    ("*/scripts/handlers/*.py",                   "handler"),
    ("*/scripts/git-hooks/*.sh",                  "git-hook"),

    # ── Domain layer — specific shapes FIRST, generic catch-all last ──
    ("*/iron-laws/domain/iron-laws.yaml",         "iron-law-registry"),
    ("*/domain/*rubric*.yaml",                    "rubric-yaml"),
    ("*/domain/*rubric*.yml",                     "rubric-yaml"),
    ("*/domain/*checklist*.yaml",                 "checklist-yaml"),
    ("*/domain/*checklist*.yml",                  "checklist-yaml"),
    ("*/skills/*/domain/schemas/*.schema.json",   "domain-schema"),
    ("*/skills/*/domain/*.yaml",                  "domain-yaml"),
    ("*/skills/*/domain/*.yml",                   "domain-yaml"),
    ("*/skills/*/application/*.py",               "application-py"),
    ("*/skills/*/references/*.md",                "generated-ref"),

    # ── Tests + plans + routine schemas ──
    ("*/tests/test_*.py",                         "test"),
    ("*/plans/*.md",                              "plan"),
    ("*/plans/*.jsonl",                           "jsonl-deliverable"),
    ("*/brainstorms/*.jsonl",                     "jsonl-deliverable"),
    ("*/brainstorms/*.md",                        "brainstorm"),
    ("*/inventory/*.jsonl",                       "jsonl-deliverable"),
    ("*/audits/*.jsonl",                          "jsonl-deliverable"),
    ("*/audits/*.md",                             "audit-report"),
    ("*/schemas/*/schema.yaml",                   "routine-schema"),

    # ── Cross-skill assets (top-level schemas, starters, templates) ──
    ("*/assets/schemas/*.schema.json",            "cross-skill-schema"),
    ("*/assets/starters/*",                       "starter-asset"),
    ("*/assets/templates/*",                      "template-asset"),

    # ── Workflow state files (per CLAUDE.md namespace ownership table) ──
    ("*/workflow/backlog.json",                   "backlog-source"),
    ("*/workflow/backlog.md",                     "backlog-md"),
    ("*/workflow/state.json",                     "workflow-state"),
    ("*/workflow/progress.md",                    "architecture-log"),
    ("*/workflow/deletions.jsonl",                "deletion-log"),
    ("*/workflow.json",                           "workflow-config"),

    # ── Bin wrappers + plugin manifest ──
    ("*/bin/kaizen-*",                            "bin-wrapper"),
    ("*/.claude-plugin/plugin.json",              "plugin-manifest"),
]

ALWAYS_EXCLUDE = [
    "*/__pycache__/*", "*/.git/*", "*.pyc", "*.pyo",
    "*/node_modules/*", "*/.venv/*", "*/venv/*",
    "*/.ruff_cache/*", "*/.pytest_cache/*", "*/.mypy_cache/*",
    "*/dist/*", "*/build/*", "*.egg-info/*",
]
MAX_SIZE_DEFAULT = 200_000

EXT_TO_LANG = {
    "py": "python", "sh": "bash", "bash": "bash",
    "js": "javascript", "cjs": "javascript", "mjs": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "rs": "rust", "go": "go", "rb": "ruby",
    "md": "markdown", "rst": "rst",
    "html": "html", "css": "css",
    "yaml": "yaml", "yml": "yaml",
    "json": "json", "jsonl": "json", "ndjson": "json",
    "toml": "toml", "ini": "ini", "cfg": "ini", "conf": "ini",
    "env": "bash", "xml": "xml", "csv": "csv", "tsv": "csv", "dot": "dot",
    "schema.json": "json",
    "Dockerfile": "dockerfile", "Makefile": "makefile",
    ".gitignore": "gitignore", ".mcp.json": "json",
}

# ─── Core walk ────────────────────────────────────────────────────

def file_type(p: Path, rel_path: str | None = None) -> str | None:
    """Return the canonical type label for p, or None if it doesn't match.

    Resolution (first match wins):
      1. PATH_PATTERNS — semantic role (skill / command / mcp / hook / …)
      2. .schema.json double-extension
      3. Bare-name files (LICENSE / Dockerfile / .mcp.json / …)
      4. File extension lookup against CANONICAL_TYPES
    """
    # Pattern-based semantic types (skill / command / mcp / hook / test / …)
    if rel_path is not None:
        for pat, label in PATH_PATTERNS:
            if fnmatch.fnmatchcase(rel_path, pat):
                return label
    name = p.name
    if name.endswith(".schema.json"):
        return "schema.json"
    if name in _BARENAMES:
        return name
    suf = p.suffix.lstrip(".")
    return suf if suf in CANONICAL_TYPES else None


def matches_any(path_str: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path_str, pat) for pat in patterns)


def _rel_for_walk(p: Path, root: Path) -> str:
    """Relative path from root.parent (so PATH_PATTERNS see */skills/* etc.)."""
    anchor = root.parent if root.parent != Path() else root
    return str(p.relative_to(anchor))


def iter_files(root: Path, types: list[str],
               include: list[str], exclude: list[str]) -> list[Path]:
    """Yield every file under root matching the type + glob filters."""
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = _rel_for_walk(p, root)
        if matches_any(rel, ALWAYS_EXCLUDE):
            continue
        t = file_type(p, rel)
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
        rel = _rel_for_walk(p, root)
        content, truncated = read_safe(p, max_size)
        rec = {
            "path": rel,
            "type": file_type(p, rel),
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

_EMITTERS = {
    "markdown": (emit_markdown, "md"),
    "jsonl":    (emit_jsonl,    "jsonl"),
    "raw":      (emit_raw,      "raw"),
}


def _bucketize_by_type(files: list[Path], root: Path) -> dict[str, list[Path]]:
    buckets: dict[str, list[Path]] = {}
    for p in files:
        t = file_type(p, _rel_for_walk(p, root)) or "unknown"
        buckets.setdefault(t, []).append(p)
    return buckets


def _safe_type_filename(t: str) -> str:
    """Turn a type label into a filesystem-safe filename stem."""
    return t.replace(".", "-").lstrip("-") or "unknown"


def cmd_dump(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    types = args.type or (CANONICAL_TYPES + [label for _, label in PATH_PATTERNS])
    files = iter_files(root, types, args.include, args.exclude)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1

    emit_fn, file_ext = _EMITTERS[args.format]

    # ── Split-by-type mode: one file per type in --out (treated as dir) ──
    if args.split:
        if not args.out:
            print("--split requires --out DIR", file=sys.stderr)
            return 2
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        buckets = _bucketize_by_type(files, root)
        for t in sorted(buckets):
            stem = _safe_type_filename(t)
            target = out_dir / f"{stem}.{file_ext}"
            with open(target, "w", encoding="utf-8") as f:
                if args.format == "markdown":
                    f.write(f"# inventory dump — type={t}, root={root}\n")
                    f.write(f"\n{len(buckets[t])} files. Max size: {args.max_size}.\n")
                emit_fn(buckets[t], root, args.max_size, f)
            print(f"  {t:14s} {len(buckets[t]):>5d} files → {target}", file=sys.stderr)
        total = sum(len(v) for v in buckets.values())
        print(f"wrote {total} files across {len(buckets)} type buckets in {out_dir}",
              file=sys.stderr)
        return 0

    # ── Single-stream mode (default) ──
    out_stream = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        if args.format == "markdown":
            out_stream.write(f"# inventory dump — {root}\n")
            out_stream.write(f"\n{len(files)} files matched. "
                              f"Types: {','.join(types)}. Max size: {args.max_size}.\n")
        emit_fn(files, root, args.max_size, out_stream)
    finally:
        if args.out:
            out_stream.close()
            print(f"wrote {len(files)} files to {args.out}", file=sys.stderr)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    types = args.type or (CANONICAL_TYPES + [label for _, label in PATH_PATTERNS])
    files = iter_files(root, types, args.include, args.exclude)
    if args.json:
        rows = []
        for p in files:
            rel = _rel_for_walk(p, root)
            rows.append({"path": rel, "type": file_type(p, rel), "bytes": p.stat().st_size})
        print(json.dumps(rows, indent=2))
    else:
        for p in files:
            rel = p.relative_to(root.parent if root.name == "kaizen" else root)
            print(rel)
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    """Report % conformance to established path patterns.

    A file is either:
      pattern    — matched one of PATH_PATTERNS (semantic role known)
      extension  — matched only by extension (generic data/config/code)
      orphan     — neither (e.g. files in unexpected locations)

    Drift % = (extension + orphan) / total — i.e. how much of the tree
    sits outside the canonical kaizen-plugin shape.
    """
    root = args.root.resolve()
    types = CANONICAL_TYPES + [label for _, label in PATH_PATTERNS]
    # Walk EVERYTHING; we want to count orphans too.
    counts = {"pattern": 0, "extension": 0, "orphan": 0}
    by_pattern: dict[str, int] = {}
    orphans: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = _rel_for_walk(p, root)
        if matches_any(rel, ALWAYS_EXCLUDE):
            continue
        # Did a path-pattern match?
        pattern_label = None
        for pat, label in PATH_PATTERNS:
            if fnmatch.fnmatchcase(rel, pat):
                pattern_label = label
                break
        if pattern_label:
            counts["pattern"] += 1
            by_pattern[pattern_label] = by_pattern.get(pattern_label, 0) + 1
            continue
        # Extension-only match?
        ext_t = file_type(p, None)  # skip patterns, use ext-only branch
        if ext_t and ext_t not in [l for _, l in PATH_PATTERNS]:
            counts["extension"] += 1
        else:
            counts["orphan"] += 1
            orphans.append(rel)

    total = sum(counts.values())
    pct = lambda n: (100.0 * n / total) if total else 0.0
    drift_n = counts["extension"] + counts["orphan"]
    drift_pct = pct(drift_n)

    if args.json:
        print(json.dumps({
            "root": str(root),
            "total": total,
            "pattern_matched": counts["pattern"],
            "extension_only": counts["extension"],
            "orphan": counts["orphan"],
            "drift_pct": round(drift_pct, 2),
            "by_pattern": by_pattern,
            "orphans": orphans[:25],
        }, indent=2))
        return 0

    print(f"inventory drift — {root}")
    print(f"  total files:        {total}")
    print(f"  matched a pattern:  {counts['pattern']:>4d}  ({pct(counts['pattern']):.1f}%)")
    print(f"  extension-only:     {counts['extension']:>4d}  ({pct(counts['extension']):.1f}%)")
    print(f"  orphan:             {counts['orphan']:>4d}  ({pct(counts['orphan']):.1f}%)")
    print(f"  drift %:            {drift_pct:.1f}%  (extension-only + orphan vs total)")
    print()
    print("  by pattern (top 10):")
    for label in sorted(by_pattern, key=lambda x: -by_pattern[x])[:10]:
        print(f"    {label:18s} {by_pattern[label]:>5d}")
    if orphans:
        print()
        print(f"  orphan-bucket sample (first 10 of {len(orphans)}):")
        for o in orphans[:10]:
            print(f"    {o}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    # Include pattern-based labels alongside canonical extensions so we
    # walk every file the iter_files filter would accept.
    types = CANONICAL_TYPES + [label for _, label in PATH_PATTERNS]
    files = iter_files(root, types, [], [])
    by_type: dict[str, dict[str, int]] = {}
    for p in files:
        t = file_type(p, _rel_for_walk(p, root)) or "?"
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
    p.add_argument("--type", action="append", metavar="TYPE",
                    help=f"file type to include (repeatable; default = all canonical: "
                         f"{','.join(CANONICAL_TYPES[:8])},…)")
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
    p_dump.add_argument("--split", action="store_true",
                        help="emit one file per type into --out DIR instead of one combined bundle")
    p_dump.set_defaults(func=cmd_dump)

    p_list = sub.add_parser("list", help="list matching paths (no content)")
    _add_filter_args(p_list)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_stats = sub.add_parser("stats", help="per-type counts + bytes")
    p_stats.add_argument("--root", type=Path, default=_detect_root())
    p_stats.set_defaults(func=cmd_stats)

    p_drift = sub.add_parser("drift",
        help="drift report against established PATH_PATTERNS (pattern / ext / orphan)")
    p_drift.add_argument("--root", type=Path, default=_detect_root())
    p_drift.add_argument("--json", action="store_true")
    p_drift.set_defaults(func=cmd_drift)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
