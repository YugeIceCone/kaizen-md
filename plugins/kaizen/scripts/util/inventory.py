#!/usr/bin/env python3
"""kaizen-inventory — walk a plugin tree, dump file contents to a bundle.

Stdlib-only. Recursive walk with type + glob filtering. Designed for
feeding agents / grep / external review.

## Subcommands

  dump          emit file contents with path headers + per-file enrichment
  list          paths matching filters (text or json)
  stats         per-type counts + bytes
  drift         % match against established PATH_PATTERNS
  tree          directory tree + per-leaf metadata
  outline       markdown headings + py docstrings across all files
  map           symbol map per file (class / function / method / heading / key)
  grep-symbol   search the extracted symbol index by name

## Per-file enrichment (jsonl format)

Each record carries: path / type / bytes / lines / nonblank_lines /
comment_lines / tokens / sha256 / truncated / content / symbols
(+ imports / imported_by under --with-graph)
(+ validation_status under --validate)

## Filters

  --type T          include type (repeatable)
  --not-type T      exclude type (repeatable)
  --include GLOB    restrict to glob (repeatable)
  --exclude GLOB    skip glob (repeatable)
  --mtime-since SPEC  '7d' / '24h' / '2026-01-01' / unix-ts
  --git-since REV   files changed since git rev (git diff REV...HEAD)
  --min-lines N     skip near-empty files
  --max-lines N     skip anomalously-large files
  --dedupe          collapse same-sha256 files (keep one)
  --budget N        stop emitting after N total tokens
  --max-size BYTES  skip files larger than (default 200KB) — replaces with stub

## Formats

  markdown          fenced-codeblock-per-file (default)
  jsonl             one record per file
  raw               >>> <path> separator, no fencing
  html              self-contained .html with <details> collapsibles
  + --split DIR     one bundle per type into DIR (markdown/jsonl/raw)
  + --sqlite DB     write queryable SQLite catalog
  + --for-rag       chunk files into ~1000-token windows for RAG indexing
  + --for-llm       structure tree header + ranked symbols + truncate tail
  + --validate      emit validation_status per file (where a schema applies)
"""
from __future__ import annotations

import argparse
import ast
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ─── Defaults ─────────────────────────────────────────────────────

CANONICAL_TYPES = [
    "py", "sh", "bash", "js", "cjs", "mjs", "ts", "tsx", "rs", "go", "rb",
    "md", "rst", "html", "css",
    "yaml", "yml", "json", "jsonl", "ndjson", "toml", "ini", "cfg", "conf",
    "env", "xml", "csv", "tsv", "dot",
    "schema.json",
    "LICENSE", "README", "CHANGELOG", "CONTRIBUTING", "Dockerfile",
    "Makefile", ".gitignore", ".mcp.json",
]

_BARENAMES = {"LICENSE", "README", "CHANGELOG", "CONTRIBUTING",
              "Dockerfile", "Makefile", ".gitignore", ".mcp.json"}

PATH_PATTERNS: list[tuple[str, str]] = [
    ("CLAUDE.md",                                 "claude-md"),
    ("*/CLAUDE.md",                               "claude-md"),
    ("*/AGENTS.md",                               "agents-md"),
    ("*/MEMORY.md",                               "memory-index"),
    ("*/skills/*/SKILL.md",                       "skill"),
    ("*/SKILL.md",                                "skill"),
    ("*/commands/*.md",                           "command"),
    ("*/commands/*/*.md",                         "command"),
    ("*/agents/*.md",                             "agent"),
    ("*/hooks/claude/*.sh",                       "hook-sh"),
    ("*/hooks/claude/*.py",                       "hook-py"),
    ("*/hooks/hooks.json",                        "hook-registry"),
    ("*/scripts/mcp/*_mcp.py",                    "mcp"),
    ("*/scripts/indexers/*.py",                   "indexer"),
    ("*/scripts/handlers/*.py",                   "handler"),
    ("*/scripts/git-hooks/*.sh",                  "git-hook"),
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
    ("*/tests/test_*.py",                         "test"),
    ("*/plans/*.md",                              "plan"),
    ("*/plans/*.jsonl",                           "jsonl-deliverable"),
    ("*/brainstorms/*.jsonl",                     "jsonl-deliverable"),
    ("*/brainstorms/*.md",                        "brainstorm"),
    ("*/inventory/*.jsonl",                       "jsonl-deliverable"),
    ("*/audits/*.jsonl",                          "jsonl-deliverable"),
    ("*/audits/*.md",                             "audit-report"),
    ("*/schemas/*/schema.yaml",                   "routine-schema"),
    ("*/assets/schemas/*.schema.json",            "cross-skill-schema"),
    ("*/assets/starters/*",                       "starter-asset"),
    ("*/assets/templates/*",                      "template-asset"),
    ("*/workflow/backlog.json",                   "backlog-source"),
    ("*/workflow/backlog.md",                     "backlog-md"),
    ("*/workflow/state.json",                     "workflow-state"),
    ("*/workflow/progress.md",                    "architecture-log"),
    ("*/workflow/deletions.jsonl",                "deletion-log"),
    ("*/workflow.json",                           "workflow-config"),
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

# Union of every label iter_files knows about — kept here so we don't
# rebuild the list in three places (cmd_dump / cmd_stats / cmd_drift /
# grep-symbol / _resolve_types).
ALL_TYPES = CANONICAL_TYPES + [label for _, label in PATH_PATTERNS]

_PY_TYPES = {"py", "test", "mcp", "indexer", "handler", "application-py", "hook-py"}
_MD_TYPES = {"md", "skill", "command", "agent", "plan", "audit-report",
             "brainstorm", "generated-ref", "claude-md", "memory-index",
             "agents-md", "backlog-md", "architecture-log"}
_YAML_TYPES = {"yaml", "yml", "domain-yaml", "rubric-yaml", "checklist-yaml",
               "iron-law-registry", "routine-schema"}
_HASH_COMMENT_TYPES = _PY_TYPES | {"sh", "bash", "hook-sh", "git-hook"} | _YAML_TYPES

# ─── Core walk ────────────────────────────────────────────────────


def file_type(p: Path, rel_path: str | None = None) -> str | None:
    """Return canonical type label. Resolution: PATH_PATTERNS → .schema.json →
    bare-name → file extension."""
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
    anchor = root.parent if root.parent != Path() else root
    return str(p.relative_to(anchor))


def iter_files(root: Path, types: list[str], include: list[str],
                exclude: list[str], not_types: list[str] | None = None) -> list[Path]:
    not_types = not_types or []
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
        if t in not_types:
            continue
        if include and not matches_any(rel, include):
            continue
        if exclude and matches_any(rel, exclude):
            continue
        out.append(p)
    return out


def read_safe(p: Path, max_size: int) -> tuple[str, bool]:
    try:
        size = p.stat().st_size
        if size > max_size:
            return (f"[skipped — {size} bytes > {max_size} max]", True)
        return (p.read_text(encoding="utf-8", errors="replace"), False)
    except OSError as e:
        return (f"[read error: {e}]", True)


# ─── Per-file enrichment (Batch A) ───────────────────────────────


def estimate_tokens(content: str) -> int:
    """Approximate GPT/Claude tokens — KISS chars/4."""
    return max(1, len(content) // 4)


def sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def loc_stats(content: str, t: str | None) -> dict:
    lines = content.splitlines()
    total = len(lines)
    nonblank = sum(1 for l in lines if l.strip())
    comment = 0
    if t in _HASH_COMMENT_TYPES:
        comment = sum(1 for l in lines if l.lstrip().startswith("#"))
    return {"lines": total, "nonblank_lines": nonblank, "comment_lines": comment}


def extract_py_symbols(content: str) -> list[dict]:
    out = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return out
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append({"kind": "class", "name": node.name, "line": node.lineno})
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append({"kind": "method", "name": item.name,
                                 "line": item.lineno, "parent": node.name})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({"kind": "function", "name": node.name, "line": node.lineno})
    return out


def extract_md_headings(content: str) -> list[dict]:
    out = []
    for i, line in enumerate(content.splitlines(), 1):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            out.append({"kind": f"h{len(m.group(1))}",
                          "name": m.group(2).strip(), "line": i})
    return out


def extract_yaml_top_keys(content: str) -> list[dict]:
    out = []
    for i, line in enumerate(content.splitlines(), 1):
        if line.startswith(" ") or line.startswith("\t") or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_][\w-]*):", line)
        if m:
            out.append({"kind": "key", "name": m.group(1), "line": i})
    return out


def extract_symbols(content: str, t: str | None) -> list[dict]:
    if t in _PY_TYPES:
        return extract_py_symbols(content)
    if t in _MD_TYPES:
        return extract_md_headings(content)
    if t in _YAML_TYPES:
        return extract_yaml_top_keys(content)
    return []


def first_docstring(content: str) -> str | None:
    try:
        return ast.get_docstring(ast.parse(content))
    except (SyntaxError, ValueError):
        return None


# ─── Import graph (Batch E) ──────────────────────────────────────


def extract_py_imports(content: str) -> list[str]:
    out = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module.split(".")[0])
    return list(dict.fromkeys(out))


def build_import_graph(files: list[Path]) -> tuple[dict, dict]:
    """Return (imports_by_path, imported_by_stem).

    imports_by_path : {abs_path_str: [imported_module_stem, ...]}
    imported_by_stem: {module_stem: [abs_path_str_of_consumer, ...]}
    """
    imports_by: dict[str, list[str]] = {}
    consumers: dict[str, list[str]] = {}
    for p in files:
        if p.suffix != ".py":
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        imps = extract_py_imports(content)
        imports_by[str(p)] = imps
    # Build inverted index keyed by module stem (the py basename without .py)
    by_stem = {p.stem: str(p) for p in files if p.suffix == ".py"}
    for src, imps in imports_by.items():
        for imp in imps:
            if imp in by_stem:
                consumers.setdefault(imp, []).append(Path(src).stem)
    return imports_by, consumers


# ─── Filters (Batch C) ────────────────────────────────────────────


def parse_mtime_since(spec: str) -> float:
    """'7d' / '24h' / '2026-01-01' / unix-ts → float seconds-since-epoch."""
    if spec.endswith("d"):
        return time.time() - int(spec[:-1]) * 86400
    if spec.endswith("h"):
        return time.time() - int(spec[:-1]) * 3600
    if spec.endswith("m"):
        return time.time() - int(spec[:-1]) * 60
    try:
        dt = datetime.datetime.fromisoformat(spec)
        return dt.timestamp()
    except ValueError:
        return float(spec)


def git_changed_since(root: Path, rev: str) -> set[str] | None:
    """Return set of paths (relative to git root) changed since rev, or None
    if git is unavailable / no repo."""
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", f"{rev}...HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        return {line.strip() for line in r.stdout.splitlines() if line.strip()}
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def apply_post_filters(files: list[Path], root: Path, args) -> list[Path]:
    out = list(files)

    # --mtime-since
    if getattr(args, "mtime_since", None):
        since = parse_mtime_since(args.mtime_since)
        out = [p for p in out if p.stat().st_mtime >= since]

    # --git-since
    if getattr(args, "git_since", None):
        changed = git_changed_since(root, args.git_since)
        if changed is not None:
            try:
                git_top = Path(subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                    text=True, timeout=10).strip())
                out = [p for p in out
                          if str(p.relative_to(git_top)) in changed]
            except (subprocess.SubprocessError, ValueError):
                pass

    # --min-lines / --max-lines
    if getattr(args, "min_lines", None) or getattr(args, "max_lines", None):
        filtered = []
        for p in out:
            try:
                n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                continue
            if args.min_lines and n < args.min_lines:
                continue
            if args.max_lines and n > args.max_lines:
                continue
            filtered.append(p)
        out = filtered

    # --dedupe (by sha256)
    if getattr(args, "dedupe", False):
        seen = {}
        dedup = []
        for p in out:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            h = sha256_of(content)
            if h not in seen:
                seen[h] = p
                dedup.append(p)
        out = dedup

    return out


# ─── Schema validation (Batch D) ─────────────────────────────────

def validate_against_schema(content: str, t: str | None) -> str:
    """Best-effort validation. Returns 'ok' / 'errors:<msg>' / 'no-schema'."""
    if t in ("json", "jsonl", "schema.json", "domain-schema",
             "cross-skill-schema", "ndjson"):
        try:
            if t in ("jsonl", "ndjson"):
                for line in content.splitlines():
                    if line.strip():
                        json.loads(line)
            else:
                json.loads(content)
            return "ok"
        except json.JSONDecodeError as e:
            return f"errors:{e}"
    if t in _YAML_TYPES:
        try:
            import yaml  # stdlib? no, but kaizen ships it. fall back if absent.
            yaml.safe_load(content)
            return "ok"
        except ImportError:
            return "no-schema"
        except Exception as e:
            return f"errors:{e}"
    if t in _PY_TYPES:
        try:
            ast.parse(content)
            return "ok"
        except SyntaxError as e:
            return f"errors:{e}"
    return "no-schema"


# ─── Output emitters ──────────────────────────────────────────────


def _record_for(p: Path, root: Path, max_size: int, with_graph: bool,
                graph: tuple[dict, dict] | None, validate: bool) -> dict:
    rel = _rel_for_walk(p, root)
    t = file_type(p, rel)
    content, truncated = read_safe(p, max_size)
    loc = loc_stats(content, t) if not truncated else {"lines": 0, "nonblank_lines": 0, "comment_lines": 0}
    rec = {
        "path": rel,
        "type": t,
        "bytes": p.stat().st_size,
        "lines": loc["lines"],
        "nonblank_lines": loc["nonblank_lines"],
        "comment_lines": loc["comment_lines"],
        "tokens": estimate_tokens(content) if not truncated else 0,
        "sha256": sha256_of(content),
        "truncated": truncated,
        "symbols": extract_symbols(content, t) if not truncated else [],
        "content": content,
    }
    if with_graph and graph:
        imports_by, consumers = graph
        rec["imports"] = imports_by.get(str(p), [])
        rec["imported_by"] = consumers.get(p.stem, [])
    if validate:
        rec["validation_status"] = validate_against_schema(content, t)
    return rec


def _lang_for(rec_type: str | None, p: Path) -> str:
    """Resolve a syntax-highlighting language tag from the record's
    semantic type, falling back to the file's actual extension when
    the semantic label isn't directly mapped."""
    if rec_type and rec_type in EXT_TO_LANG:
        return EXT_TO_LANG[rec_type]
    suf = p.suffix.lstrip(".")
    return EXT_TO_LANG.get(suf, "")


def emit_markdown(files: list[Path], root: Path, args, out) -> None:
    """Per-file shape (consistent across the bundle):

        ## `<rel/path>`

        > type: <T> · bytes: <N> · lines: <N> · tokens: <N> · sha: <12hex>

        ```<lang>
        <content>
        ```

    Downstream parsers can chunk reliably on `^## `\\``; pull metadata
    via `^> type:`; and trust the fenced language tag for syntax-hi.
    """
    for p in files:
        rec = _record_for(p, root, args.max_size, False, None, False)
        lang = _lang_for(rec["type"], p)
        sha_short = (rec["sha256"] or "")[:12]
        meta = (f"> type: {rec['type'] or '?'} · "
                f"bytes: {rec['bytes']} · "
                f"lines: {rec['lines']} · "
                f"tokens: {rec['tokens']} · "
                f"sha: {sha_short}")
        out.write(f"\n## `{rec['path']}`\n\n{meta}\n\n")
        out.write(f"```{lang}\n{rec['content']}\n```\n")


def emit_jsonl(files: list[Path], root: Path, args, out) -> None:
    graph = build_import_graph(files) if getattr(args, "with_graph", False) else None
    for p in files:
        rec = _record_for(p, root, args.max_size,
                            getattr(args, "with_graph", False), graph,
                            getattr(args, "validate", False))
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")


def emit_raw(files: list[Path], root: Path, args, out) -> None:
    for p in files:
        rel = _rel_for_walk(p, root)
        content, _ = read_safe(p, args.max_size)
        out.write(f"\n>>> {rel}\n")
        out.write(content)
        if not content.endswith("\n"):
            out.write("\n")


def emit_html(files: list[Path], root: Path, args, out) -> None:
    out.write("<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
              "<title>inventory dump</title>"
              "<style>body{font-family:sans-serif;max-width:100ch;margin:2em auto;}"
              "details{margin:0.4em 0;}summary{cursor:pointer;font-family:monospace;}"
              "pre{background:#f4f4f4;padding:1em;overflow:auto;}</style>"
              "</head><body>\n")
    out.write(f"<h1>inventory dump — {root}</h1>\n")
    for p in files:
        rel = _rel_for_walk(p, root)
        t = file_type(p, rel) or ""
        content, _ = read_safe(p, args.max_size)
        # Escape minimally
        esc = (content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        out.write(f"<details><summary>{rel} <small>· {t}</small></summary>\n")
        out.write(f"<pre><code>{esc}</code></pre></details>\n")
    out.write("</body></html>\n")


def emit_for_rag(files: list[Path], root: Path, args, out,
                  window: int = 1000, overlap: int = 100) -> None:
    """Chunk each file into ~window-token windows with line metadata."""
    for p in files:
        rel = _rel_for_walk(p, root)
        t = file_type(p, rel)
        content, truncated = read_safe(p, args.max_size)
        if truncated:
            continue
        lines = content.splitlines(keepends=True)
        # Greedy chunk by line until ~window tokens hit
        chunk_idx = 0
        i = 0
        while i < len(lines):
            chunk_lines = []
            chunk_tokens = 0
            start_line = i + 1
            while i < len(lines) and chunk_tokens < window:
                chunk_lines.append(lines[i])
                chunk_tokens += estimate_tokens(lines[i])
                i += 1
            end_line = i
            rec = {
                "path": rel,
                "type": t,
                "chunk_index": chunk_idx,
                "line_start": start_line,
                "line_end": end_line,
                "tokens": chunk_tokens,
                "content": "".join(chunk_lines),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            chunk_idx += 1
            # overlap: rewind by ~overlap tokens
            if overlap and i < len(lines):
                back = 0
                j = i - 1
                while j > start_line - 1 and back < overlap:
                    back += estimate_tokens(lines[j])
                    j -= 1
                i = max(start_line, j + 1)


def emit_sqlite(files: list[Path], root: Path, args, db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY, path TEXT UNIQUE, type TEXT,
                bytes INTEGER, lines INTEGER, sha256 TEXT, tokens INTEGER);
            CREATE TABLE IF NOT EXISTS symbols (
                file_id INTEGER REFERENCES files(id),
                kind TEXT, name TEXT, line INTEGER);
            CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
        """)
        for p in files:
            rec = _record_for(p, root, args.max_size, False, None, False)
            cur = con.execute(
                "INSERT OR REPLACE INTO files (path,type,bytes,lines,sha256,tokens) "
                "VALUES (?,?,?,?,?,?)",
                (rec["path"], rec["type"], rec["bytes"], rec["lines"],
                 rec["sha256"], rec["tokens"]))
            fid = cur.lastrowid
            for s in rec["symbols"]:
                con.execute(
                    "INSERT INTO symbols (file_id,kind,name,line) VALUES (?,?,?,?)",
                    (fid, s["kind"], s["name"], s["line"]))
        con.commit()
    finally:
        con.close()


_EMITTERS = {
    "markdown": (emit_markdown, "md"),
    "jsonl":    (emit_jsonl,    "jsonl"),
    "raw":      (emit_raw,      "raw"),
    "html":     (emit_html,     "html"),
}


def _bucketize_by_type(files: list[Path], root: Path) -> dict[str, list[Path]]:
    buckets: dict[str, list[Path]] = {}
    for p in files:
        t = file_type(p, _rel_for_walk(p, root)) or "unknown"
        buckets.setdefault(t, []).append(p)
    return buckets


def _safe_type_filename(t: str) -> str:
    return t.replace(".", "-").lstrip("-") or "unknown"


# ─── Subcommands ──────────────────────────────────────────────────


def _resolve_types(args) -> list[str]:
    return args.type or (ALL_TYPES)


def _resolved_files(args) -> tuple[Path, list[Path]]:
    root = args.root.resolve()
    types = _resolve_types(args)
    not_types = getattr(args, "not_type", None) or []
    files = iter_files(root, types, args.include, args.exclude, not_types=not_types)
    files = apply_post_filters(files, root, args)
    return root, files


def _structure_tree(root: Path, files: list[Path]) -> str:
    """Return a directory tree string."""
    lines = ["## Structure", ""]
    by_dir: dict[str, list[Path]] = {}
    for p in files:
        rel = _rel_for_walk(p, root)
        by_dir.setdefault(str(Path(rel).parent), []).append(p)
    for d in sorted(by_dir):
        lines.append(f"  {d}/")
        for p in sorted(by_dir[d]):
            lines.append(f"    {Path(_rel_for_walk(p, root)).name}")
    return "\n".join(lines)


def cmd_dump(args) -> int:
    root, files = _resolved_files(args)
    if not files:
        print("no files matched", file=sys.stderr)
        return 1

    # --sqlite path: write catalog and return
    if getattr(args, "sqlite", None):
        emit_sqlite(files, root, args, Path(args.sqlite))
        print(f"wrote SQLite catalog to {args.sqlite}: {len(files)} files",
              file=sys.stderr)
        return 0

    # --for-rag: jsonl chunked output
    if getattr(args, "for_rag", False):
        out_stream = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
        try:
            emit_for_rag(files, root, args, out_stream)
        finally:
            if args.out:
                out_stream.close()
                print(f"wrote chunked RAG bundle to {args.out}", file=sys.stderr)
        return 0

    # --budget: trim files greedily by token-count signal
    if getattr(args, "budget", None):
        ranked = sorted(files, key=lambda p: p.stat().st_size)
        kept, total = [], 0
        for p in ranked:
            try:
                tk = estimate_tokens(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if total + tk > args.budget:
                continue
            kept.append(p)
            total += tk
        files = kept

    emit_fn, file_ext = _EMITTERS[args.format]

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
                    f.write(f"# inventory dump — type={t}, root={root}\n\n"
                            f"{len(buckets[t])} files.\n")
                emit_fn(buckets[t], root, args, f)
            print(f"  {t:18s} {len(buckets[t]):>5d} files → {target}", file=sys.stderr)
        total = sum(len(v) for v in buckets.values())
        print(f"wrote {total} files across {len(buckets)} type buckets in {out_dir}",
              file=sys.stderr)
        return 0

    out_stream = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        if args.format == "markdown":
            out_stream.write(f"# inventory dump — {root}\n\n"
                              f"{len(files)} files matched.\n")
            if getattr(args, "for_llm", False):
                out_stream.write("\n" + _structure_tree(root, files) + "\n")
        emit_fn(files, root, args, out_stream)
    finally:
        if args.out:
            out_stream.close()
            print(f"wrote {len(files)} files to {args.out}", file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    root, files = _resolved_files(args)
    if args.json:
        rows = [{"path": _rel_for_walk(p, root),
                  "type": file_type(p, _rel_for_walk(p, root)),
                  "bytes": p.stat().st_size}
                 for p in files]
        print(json.dumps(rows, indent=2))
    else:
        for p in files:
            print(_rel_for_walk(p, root))
    return 0


def cmd_stats(args) -> int:
    root = args.root.resolve()
    types = ALL_TYPES
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
        print(f"  {t:18s} {s['count']:6d} files  {s['bytes']:>10d} bytes")
    return 0


def cmd_drift(args) -> int:
    root = args.root.resolve()
    counts = {"pattern": 0, "extension": 0, "orphan": 0}
    by_pattern: dict[str, int] = {}
    orphans: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = _rel_for_walk(p, root)
        if matches_any(rel, ALWAYS_EXCLUDE):
            continue
        pattern_label = None
        for pat, label in PATH_PATTERNS:
            if fnmatch.fnmatchcase(rel, pat):
                pattern_label = label
                break
        if pattern_label:
            counts["pattern"] += 1
            by_pattern[pattern_label] = by_pattern.get(pattern_label, 0) + 1
            continue
        ext_t = file_type(p, None)
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
            "root": str(root), "total": total,
            "pattern_matched": counts["pattern"],
            "extension_only": counts["extension"],
            "orphan": counts["orphan"],
            "drift_pct": round(drift_pct, 2),
            "by_pattern": by_pattern, "orphans": orphans[:25],
        }, indent=2))
        return 0
    print(f"inventory drift — {root}")
    print(f"  total files:        {total}")
    print(f"  matched a pattern:  {counts['pattern']:>4d}  ({pct(counts['pattern']):.1f}%)")
    print(f"  extension-only:     {counts['extension']:>4d}  ({pct(counts['extension']):.1f}%)")
    print(f"  orphan:             {counts['orphan']:>4d}  ({pct(counts['orphan']):.1f}%)")
    print(f"  drift pct:          {drift_pct:.1f}%  (extension + orphan vs total)")
    print("\n  by pattern (top 10):")
    for label in sorted(by_pattern, key=lambda x: -by_pattern[x])[:10]:
        print(f"    {label:18s} {by_pattern[label]:>5d}")
    if orphans:
        print(f"\n  orphan-bucket sample (first 10 of {len(orphans)}):")
        for o in orphans[:10]:
            print(f"    {o}")
    return 0


def cmd_tree(args) -> int:
    root, files = _resolved_files(args)
    print(f"# directory tree — {root}\n")
    by_dir: dict[str, list[Path]] = {}
    for p in files:
        rel = _rel_for_walk(p, root)
        by_dir.setdefault(str(Path(rel).parent), []).append(p)
    for d in sorted(by_dir):
        print(f"  {d}/")
        for p in sorted(by_dir[d]):
            rel = _rel_for_walk(p, root)
            t = file_type(p, rel) or "?"
            print(f"    {rel:60s} · {t:14s} · {p.stat().st_size:>7d}B")
    return 0


def cmd_outline(args) -> int:
    root, files = _resolved_files(args)
    print(f"# outline — {root}\n")
    for p in files:
        rel = _rel_for_walk(p, root)
        t = file_type(p, rel)
        content, truncated = read_safe(p, args.max_size if hasattr(args, "max_size") else MAX_SIZE_DEFAULT)
        if truncated:
            continue
        if t in _PY_TYPES:
            ds = first_docstring(content)
            if ds:
                print(f"## {rel}\n    {ds.splitlines()[0]}")
        elif t in _MD_TYPES:
            syms = extract_md_headings(content)
            if syms:
                print(f"## {rel}")
                for s in syms[:10]:
                    depth = int(s["kind"][1:])
                    print(f"    {'#' * depth} {s['name']}")
    return 0


def cmd_map(args) -> int:
    root, files = _resolved_files(args)
    print(f"# symbol map — {root}\n")
    for p in files:
        rel = _rel_for_walk(p, root)
        t = file_type(p, rel)
        content, truncated = read_safe(p, args.max_size if hasattr(args, "max_size") else MAX_SIZE_DEFAULT)
        if truncated:
            continue
        syms = extract_symbols(content, t)
        if not syms:
            continue
        print(f"\n{rel}:")
        for s in syms:
            kind = s["kind"]
            if kind == "class":
                print(f"  class {s['name']}")
            elif kind == "method":
                print(f"    def {s['name']}")
            elif kind == "function":
                print(f"  def {s['name']}")
            elif kind.startswith("h"):
                print(f"  {'#' * int(kind[1:])} {s['name']}")
            elif kind == "key":
                print(f"  {s['name']}:")
    return 0


def cmd_grep_symbol(args) -> int:
    needle = args.symbol
    root = args.root.resolve()
    types = ALL_TYPES
    files = iter_files(root, types, [], [])
    hits = 0
    for p in files:
        rel = _rel_for_walk(p, root)
        t = file_type(p, rel)
        content, truncated = read_safe(p, MAX_SIZE_DEFAULT)
        if truncated:
            continue
        for s in extract_symbols(content, t):
            if needle.lower() in s["name"].lower():
                print(f"{rel}:{s['line']}  {s['kind']} {s['name']}")
                hits += 1
    return 0 if hits else 1


# ─── CLI ──────────────────────────────────────────────────────────


def _detect_root() -> Path:
    cwd = Path.cwd()
    for cand in [cwd / "plugins" / "kaizen", cwd]:
        if cand.is_dir():
            return cand
    return cwd


def _add_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--type", action="append", metavar="TYPE",
                    help="file type to include (repeatable)")
    p.add_argument("--not-type", action="append", metavar="TYPE", default=[],
                    help="file type to exclude (repeatable)")
    p.add_argument("--include", action="append", default=[], metavar="GLOB",
                    help="restrict to paths matching glob (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                    help="skip paths matching glob (repeatable)")
    p.add_argument("--root", type=Path, default=_detect_root(),
                    help="walk root")
    p.add_argument("--mtime-since", metavar="SPEC",
                    help="'7d' / '24h' / '2026-01-01' / unix-ts")
    p.add_argument("--git-since", metavar="REV",
                    help="files changed since git rev (diff REV...HEAD)")
    p.add_argument("--min-lines", type=int, metavar="N",
                    help="skip files with fewer than N lines")
    p.add_argument("--max-lines", type=int, metavar="N",
                    help="skip files with more than N lines")
    p.add_argument("--dedupe", action="store_true",
                    help="collapse files with identical sha256")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="kaizen-inventory",
        description="Walk a plugin tree; dump file contents to a bundle.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="emit file contents with path headers")
    _add_filter_args(p_dump)
    p_dump.add_argument("--out", metavar="FILE", help="write to FILE")
    p_dump.add_argument("--format",
                          choices=["markdown", "jsonl", "raw", "html"],
                          default="markdown")
    p_dump.add_argument("--max-size", type=int, default=MAX_SIZE_DEFAULT)
    p_dump.add_argument("--split", action="store_true",
                          help="emit one file per type into --out DIR")
    p_dump.add_argument("--budget", type=int, metavar="TOKENS",
                          help="stop emitting once total tokens hit budget")
    p_dump.add_argument("--with-graph", action="store_true",
                          help="add imports / imported_by to each record")
    p_dump.add_argument("--for-rag", action="store_true",
                          help="chunked windows for RAG indexing")
    p_dump.add_argument("--for-llm", action="store_true",
                          help="prepend structure-tree header")
    p_dump.add_argument("--sqlite", metavar="DB",
                          help="write queryable SQLite catalog to DB")
    p_dump.add_argument("--validate", action="store_true",
                          help="add validation_status per file")
    p_dump.set_defaults(func=cmd_dump)

    p_list = sub.add_parser("list", help="list matching paths (no content)")
    _add_filter_args(p_list)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_stats = sub.add_parser("stats", help="per-type counts + bytes")
    p_stats.add_argument("--root", type=Path, default=_detect_root())
    p_stats.set_defaults(func=cmd_stats)

    p_drift = sub.add_parser("drift",
        help="drift report against established PATH_PATTERNS")
    p_drift.add_argument("--root", type=Path, default=_detect_root())
    p_drift.add_argument("--json", action="store_true")
    p_drift.set_defaults(func=cmd_drift)

    p_tree = sub.add_parser("tree",
        help="directory tree + per-leaf metadata")
    _add_filter_args(p_tree)
    p_tree.set_defaults(func=cmd_tree)

    p_outline = sub.add_parser("outline",
        help="md headings + py docstrings across all files")
    _add_filter_args(p_outline)
    p_outline.set_defaults(func=cmd_outline)

    p_map = sub.add_parser("map",
        help="symbol map per file (class/function/method/heading/key)")
    _add_filter_args(p_map)
    p_map.set_defaults(func=cmd_map)

    p_grep = sub.add_parser("grep-symbol",
        help="search extracted symbol index by name")
    p_grep.add_argument("symbol", help="symbol name (substring, case-insensitive)")
    p_grep.add_argument("--root", type=Path, default=_detect_root())
    p_grep.set_defaults(func=cmd_grep_symbol)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
