#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cpu"
# url = "https://download.pytorch.org/whl/cpu"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cpu" }
# ///
"""kaizen onboard-index — SQLite-backed semantic search over a codebase.

Sibling of `trace_index.py` (event log) and `knowledge_index.py` (brain
notes + plans). Same model (`all-MiniLM-L6-v2`, 384-dim), same SQLite
shape, same uv-managed venv. Indexes ONE PROJECT'S source files at a
time; the db lives in the project's own `.kaizen/onboard.db` (not the
user-global `~/.claude/` tree — project-scoped, gitignorable).

## What gets indexed

- **Tracked files only** via `git ls-files` when the project is a git
  repo. Falls back to filesystem walk + ignore-list otherwise.
- **Source code only** — extensions matched against the language table
  below. Lockfiles, generated files, minified bundles, binaries,
  vendored deps are all skipped.
- **Per-file:** stripped of comments (language-aware), whitespace
  collapsed (multiple blanks → 1, trailing trimmed). What's stored +
  embedded is the cleaned content — semsearch matches on actual code
  intent, not on docstring noise.

## Languages supported (extension → strip strategy)

| Language    | Extensions                       | Comment strip      |
|-------------|----------------------------------|--------------------|
| Rust        | .rs                              | c-family           |
| Python      | .py, .pyi                        | python (# + triple-quoted) |
| JS / TS     | .js .jsx .mjs .cjs .ts .tsx      | c-family           |
| Go          | .go                              | c-family           |
| Java        | .java                            | c-family           |
| Kotlin      | .kt .kts                         | c-family           |
| Scala       | .scala                           | c-family           |
| C / C++     | .c .h .cpp .hpp .cc .hh .cxx     | c-family           |
| C#          | .cs                              | c-family           |
| Swift       | .swift                           | c-family           |
| PHP         | .php                             | c-family + hash    |
| Ruby        | .rb                              | hash + =begin/=end |
| Shell       | .sh .bash .zsh                   | hash               |
| Lua         | .lua                             | lua                |
| Elixir      | .ex .exs                         | hash               |
| Haskell     | .hs                              | haskell            |
| OCaml       | .ml .mli                         | ocaml              |
| SQL         | .sql                             | sql                |
| YAML / TOML | .yaml .yml .toml                 | hash (config files) |

## Privacy + scope

Project-scoped by default (`<repo>/.kaizen/onboard.db`). Files matching
`*secret*`, `*credential*`, `*token*` in their path are skipped entirely.
Cleaned content IS stored — there's no "signature-only" mode for code
(the value is in semantic matching of actual logic). Add `.kaizen/`
to `.gitignore` if it isn't already (the kaizen install hook does this).

## SQLite schema

    code_files:
        id          INTEGER PRIMARY KEY AUTOINCREMENT
        path        TEXT NOT NULL UNIQUE     -- relative to project root
        language    TEXT NOT NULL
        bytes       INTEGER NOT NULL         -- raw file size
        sloc        INTEGER NOT NULL         -- lines after stripping
        snippet     TEXT NOT NULL            -- first ~2KB of cleaned content
        embedding   BLOB NOT NULL            -- np.float32, dim=384
        sha         TEXT NOT NULL            -- raw content sha1[:16] for dedup
        updated_at  TEXT NOT NULL            -- file mtime ISO

    code_meta:
        key         TEXT PRIMARY KEY
        value       TEXT

## Subcommands

    index [--root PATH] [--no-git]   incremental index of new + changed files
    reindex [--root PATH] [--no-git] wipe + full reindex
    search "<query>"                 semantic cosine search
        [--top-k 10] [--lang LANG] [--json]
    stats                            counts by language, total bytes/sloc
    get <id>                         fetch one file record (snippet included)
    path                             print db path
    clear                            drop the index

## Pairing with /init

`/init` (Claude Code's built-in) writes a `CLAUDE.md` orientation doc
to the project — describes the codebase in prose. `/kaizen:onboard`
indexes the code itself for semantic retrieval. Recommended onboarding
flow:

    /init                         # writes CLAUDE.md from Claude's read-pass
    /kaizen:onboard index         # indexes the code into .kaizen/onboard.db
    /kaizen:onboard search "..."  # query for grounded answers

## Env

    KAIZEN_ONBOARD_DB        override db path (default <repo>/.kaizen/onboard.db)
    KAIZEN_ONBOARD_MODEL     override model (default all-MiniLM-L6-v2)
    KAIZEN_ONBOARD_MAX_BYTES skip files larger than this (default 1_000_000)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# ─── Constants ───────────────────────────────────────────────────────


DEFAULT_MODEL = os.environ.get("KAIZEN_ONBOARD_MODEL", "all-MiniLM-L6-v2")
DEFAULT_DIM = 384
MAX_BYTES = int(os.environ.get("KAIZEN_ONBOARD_MAX_BYTES", "1000000"))
SNIPPET_MAX = 2048

# extension → (language, strip_strategy)
LANG_TABLE: dict[str, tuple[str, str]] = {
    ".rs": ("rust", "c-family"),
    ".py": ("python", "python"),
    ".pyi": ("python", "python"),
    ".js": ("javascript", "c-family"),
    ".jsx": ("javascript", "c-family"),
    ".mjs": ("javascript", "c-family"),
    ".cjs": ("javascript", "c-family"),
    ".ts": ("typescript", "c-family"),
    ".tsx": ("typescript", "c-family"),
    ".go": ("go", "c-family"),
    ".java": ("java", "c-family"),
    ".kt": ("kotlin", "c-family"),
    ".kts": ("kotlin", "c-family"),
    ".scala": ("scala", "c-family"),
    ".c": ("c", "c-family"),
    ".h": ("c", "c-family"),
    ".cpp": ("cpp", "c-family"),
    ".hpp": ("cpp", "c-family"),
    ".cc": ("cpp", "c-family"),
    ".hh": ("cpp", "c-family"),
    ".cxx": ("cpp", "c-family"),
    ".cs": ("csharp", "c-family"),
    ".swift": ("swift", "c-family"),
    ".php": ("php", "c-family-and-hash"),
    ".rb": ("ruby", "ruby"),
    ".sh": ("shell", "hash"),
    ".bash": ("shell", "hash"),
    ".zsh": ("shell", "hash"),
    ".lua": ("lua", "lua"),
    ".ex": ("elixir", "hash"),
    ".exs": ("elixir", "hash"),
    ".hs": ("haskell", "haskell"),
    ".ml": ("ocaml", "ocaml"),
    ".mli": ("ocaml", "ocaml"),
    ".sql": ("sql", "sql"),
    ".yaml": ("yaml", "hash"),
    ".yml": ("yaml", "hash"),
    ".toml": ("toml", "hash"),
}

# Path patterns to skip even when git-tracked.
SKIP_PATH_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"(^|/)(node_modules|target|dist|build|\.git|__pycache__|\.venv|venv|vendor|\.cache|tmp|coverage|\.pytest_cache|\.mypy_cache|\.next|\.nuxt|\.output)/",
        r"\.(min|bundle)\.(js|css)$",
        r"(^|/)(package-lock\.json|yarn\.lock|Cargo\.lock|poetry\.lock|Pipfile\.lock|composer\.lock|go\.sum)$",
        r"secret",
        r"credential",
        r"token",
    )
]

# ─── Lazy ML imports ─────────────────────────────────────────────────


_model = None
_np = None


def _load_model():
    global _model, _np
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as e:
            sys.stderr.write(
                f"kaizen-onboard-index: missing dep: {e}\n"
                "PEP 723 should auto-install via uv. If running with python3 directly:\n"
                "  pip install --user sentence-transformers numpy\n"
            )
            sys.exit(1)
        _np = np
        _model = SentenceTransformer(DEFAULT_MODEL)
    return _model, _np


# ─── DB ──────────────────────────────────────────────────────────────


def db_path(root: Path) -> Path:
    """Default location: <root>/.kaizen/onboard.db. Overridable via env."""
    env = os.environ.get("KAIZEN_ONBOARD_DB")
    if env:
        return Path(env).expanduser()
    return root / ".kaizen" / "onboard.db"


def open_db(root: Path, create: bool = True) -> sqlite3.Connection:
    path = db_path(root)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    if create:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS code_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                language TEXT NOT NULL,
                bytes INTEGER NOT NULL,
                sloc INTEGER NOT NULL,
                snippet TEXT NOT NULL,
                embedding BLOB NOT NULL,
                sha TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_code_lang ON code_files(language);
            CREATE INDEX IF NOT EXISTS idx_code_path ON code_files(path);
            CREATE TABLE IF NOT EXISTS code_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO code_meta (key, value) VALUES (?, ?)", (key, value)
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM code_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


# ─── Source-file discovery ───────────────────────────────────────────


def _should_skip_path(rel_path: str) -> bool:
    return any(p.search(rel_path) for p in SKIP_PATH_PATTERNS)


def _is_source_file(path: Path) -> bool:
    return path.suffix.lower() in LANG_TABLE


def iter_tracked_files(root: Path) -> list[Path]:
    """Use `git ls-files` when available; falls back to fs walk."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        files = [root / line for line in out.split("\n") if line.strip()]
        return files
    except (subprocess.CalledProcessError, FileNotFoundError):
        return list(root.rglob("*"))


def iter_source_files(root: Path, use_git: bool = True) -> list[Path]:
    """Filter to source files only: extension match + path skip + size cap."""
    candidates = iter_tracked_files(root) if use_git else list(root.rglob("*"))
    out: list[Path] = []
    for p in candidates:
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix() if p.is_absolute() else p.as_posix()
        if _should_skip_path(rel):
            continue
        if not _is_source_file(p):
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        out.append(p)
    return out


# ─── Comment stripping ───────────────────────────────────────────────


_C_LINE = re.compile(r"//[^\n]*")
_C_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_HASH_LINE = re.compile(r"(?<!\$)#[^\n]*")  # avoid stripping ${...#...} bash patterns
_PY_TRIPLE_DOUBLE = re.compile(r'"""(.*?)"""', re.DOTALL)
_PY_TRIPLE_SINGLE = re.compile(r"'''(.*?)'''", re.DOTALL)
_RB_BLOCK = re.compile(r"^=begin\s*$.*?^=end\s*$", re.DOTALL | re.MULTILINE)
_LUA_BLOCK = re.compile(r"--\[\[.*?\]\]", re.DOTALL)
_LUA_LINE = re.compile(r"--[^\n]*")
_HASKELL_LINE = re.compile(r"--[^\n]*")
_HASKELL_BLOCK = re.compile(r"\{-.*?-\}", re.DOTALL)
_OCAML_BLOCK = re.compile(r"\(\*.*?\*\)", re.DOTALL)
_SQL_LINE = re.compile(r"--[^\n]*")
_SQL_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_comments(text: str, strategy: str) -> str:
    """Strip per-language comments. Regex-based: imperfect inside string
    literals but good enough for semantic search (false strips don't
    hurt recall, only specificity, and code typically has far more
    code-bearing chars than string-literal chars)."""
    if strategy == "c-family":
        text = _C_BLOCK.sub("", text)
        text = _C_LINE.sub("", text)
    elif strategy == "c-family-and-hash":
        text = _C_BLOCK.sub("", text)
        text = _C_LINE.sub("", text)
        text = _HASH_LINE.sub("", text)
    elif strategy == "python":
        text = _PY_TRIPLE_DOUBLE.sub("", text)
        text = _PY_TRIPLE_SINGLE.sub("", text)
        text = _HASH_LINE.sub("", text)
    elif strategy == "hash":
        text = _HASH_LINE.sub("", text)
    elif strategy == "ruby":
        text = _RB_BLOCK.sub("", text)
        text = _HASH_LINE.sub("", text)
    elif strategy == "lua":
        text = _LUA_BLOCK.sub("", text)
        text = _LUA_LINE.sub("", text)
    elif strategy == "haskell":
        text = _HASKELL_BLOCK.sub("", text)
        text = _HASKELL_LINE.sub("", text)
    elif strategy == "ocaml":
        text = _OCAML_BLOCK.sub("", text)
    elif strategy == "sql":
        text = _SQL_BLOCK.sub("", text)
        text = _SQL_LINE.sub("", text)
    return text


# ─── Whitespace normalization ────────────────────────────────────────


_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_MULTI_BLANK = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> str:
    """Trim trailing whitespace per line, collapse 3+ blank lines to one
    blank. Preserves indentation (significant for Python, helpful for
    embeddings in any language)."""
    text = _TRAILING_WS.sub("", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip() + "\n"


def count_sloc(text: str) -> int:
    """Count non-blank lines after stripping + normalizing."""
    return sum(1 for line in text.split("\n") if line.strip())


# ─── File → record ───────────────────────────────────────────────────


def _file_sha(content: bytes) -> str:
    return hashlib.sha1(content).hexdigest()[:16]


def process_file(path: Path, root: Path) -> dict | None:
    """Read + strip + normalize. Returns the record dict or None on error."""
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        return None
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary or non-UTF-8 — skip
    ext = path.suffix.lower()
    language, strategy = LANG_TABLE[ext]
    cleaned = normalize_whitespace(strip_comments(raw_text, strategy))
    snippet = cleaned[:SNIPPET_MAX]
    try:
        rel_path = path.relative_to(root).as_posix()
    except ValueError:
        rel_path = path.as_posix()
    try:
        mtime = dt.datetime.fromtimestamp(
            path.stat().st_mtime, dt.timezone.utc
        ).isoformat()
    except OSError:
        mtime = ""
    return {
        "path": rel_path,
        "language": language,
        "bytes": len(raw_bytes),
        "sloc": count_sloc(cleaned),
        "snippet": snippet,
        "cleaned_for_embed": cleaned,  # passed to embedder; not stored verbatim
        "sha": _file_sha(raw_bytes),
        "updated_at": mtime,
    }


def embed_one(text: str):
    model, np = _load_model()
    vec = model.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return vec.astype(np.float32).tobytes()


# ─── do_* helpers (data-returning; mirrored by onboard_mcp.py) ───────


def do_index(root: Path, use_git: bool = True) -> dict:
    """Run incremental indexing. Returns {new, skipped, stale_removed, total}."""
    conn = open_db(root, create=True)
    seen_paths: set[str] = set()
    new_count = 0
    skip_count = 0
    error_count = 0
    for path in iter_source_files(root, use_git=use_git):
        rec = process_file(path, root)
        if not rec:
            error_count += 1
            continue
        seen_paths.add(rec["path"])
        existing = conn.execute(
            "SELECT sha FROM code_files WHERE path = ?", (rec["path"],)
        ).fetchone()
        if existing and existing["sha"] == rec["sha"]:
            skip_count += 1
            continue
        emb = embed_one(rec["cleaned_for_embed"])
        conn.execute(
            """INSERT OR REPLACE INTO code_files
               (path, language, bytes, sloc, snippet, embedding, sha, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec["path"],
                rec["language"],
                rec["bytes"],
                rec["sloc"],
                rec["snippet"],
                emb,
                rec["sha"],
                rec["updated_at"],
            ),
        )
        new_count += 1
    # Remove stale entries (in db but no longer in tree)
    all_in_db = conn.execute("SELECT path FROM code_files").fetchall()
    stale = [r["path"] for r in all_in_db if r["path"] not in seen_paths]
    if stale:
        conn.executemany(
            "DELETE FROM code_files WHERE path = ?", [(p,) for p in stale]
        )
    set_meta(conn, "model", DEFAULT_MODEL)
    set_meta(conn, "dim", str(DEFAULT_DIM))
    set_meta(conn, "last_indexed_ts", dt.datetime.now(dt.timezone.utc).isoformat())
    total = conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
    set_meta(conn, "total_files", str(total))
    set_meta(conn, "root", str(root))
    conn.commit()
    conn.close()
    return {
        "new": new_count,
        "skipped": skip_count,
        "stale_removed": len(stale),
        "errors": error_count,
        "total": total,
        "model": DEFAULT_MODEL,
        "db": str(db_path(root)),
    }


def do_search(
    root: Path,
    query: str,
    top_k: int = 10,
    language: str | None = None,
) -> list[dict]:
    """Cosine-similarity search. Returns [{score, id, path, language, sloc, snippet, updated_at}]."""
    path = db_path(root)
    if not path.is_file():
        return []
    conn = open_db(root, create=False)
    model, np = _load_model()
    qvec = model.encode(query, convert_to_numpy=True, show_progress_bar=False).astype(
        np.float32
    )
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)
    where_sql = ""
    params: list = []
    if language:
        where_sql = " WHERE language = ?"
        params.append(language)
    rows = conn.execute(
        f"SELECT * FROM code_files{where_sql}", params
    ).fetchall()
    scored = []
    for r in rows:
        evec = np.frombuffer(r["embedding"], dtype=np.float32)
        if evec.shape[0] != DEFAULT_DIM:
            continue
        score = float(np.dot(qnorm, evec / (np.linalg.norm(evec) + 1e-12)))
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, r in scored[:top_k]:
        out.append(
            {
                "score": round(score, 4),
                "id": r["id"],
                "path": r["path"],
                "language": r["language"],
                "bytes": r["bytes"],
                "sloc": r["sloc"],
                "snippet": r["snippet"],
                "updated_at": r["updated_at"],
            }
        )
    conn.close()
    return out


def do_stats(root: Path) -> dict:
    path = db_path(root)
    if not path.is_file():
        return {"indexed": False, "db_path": str(path)}
    conn = open_db(root, create=False)
    total = conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
    total_bytes = conn.execute("SELECT COALESCE(SUM(bytes),0) FROM code_files").fetchone()[0]
    total_sloc = conn.execute("SELECT COALESCE(SUM(sloc),0) FROM code_files").fetchone()[0]
    by_lang = {
        r["language"]: r["n"]
        for r in conn.execute(
            "SELECT language, COUNT(*) AS n FROM code_files GROUP BY language ORDER BY n DESC"
        ).fetchall()
    }
    out = {
        "indexed": True,
        "db_path": str(path),
        "root": get_meta(conn, "root", ""),
        "model": get_meta(conn, "model", ""),
        "dim": get_meta(conn, "dim", ""),
        "last_indexed_ts": get_meta(conn, "last_indexed_ts", ""),
        "total": total,
        "total_bytes": total_bytes,
        "total_sloc": total_sloc,
        "by_language": by_lang,
    }
    conn.close()
    return out


def do_get(root: Path, file_id: int) -> dict | None:
    path = db_path(root)
    if not path.is_file():
        return None
    conn = open_db(root, create=False)
    r = conn.execute(
        "SELECT * FROM code_files WHERE id = ?", (file_id,)
    ).fetchone()
    conn.close()
    if not r:
        return None
    return {k: r[k] for k in r.keys() if k != "embedding"}


# ─── CLI ─────────────────────────────────────────────────────────────


def _resolve_root(args) -> Path:
    if getattr(args, "root", None):
        return Path(args.root).expanduser().resolve()
    # Default: git rev-parse --show-toplevel, else cwd
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return Path(out) if out else Path.cwd()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def cmd_index(args):
    root = _resolve_root(args)
    result = do_index(root, use_git=not args.no_git)
    print(
        f"kaizen-onboard: indexed {result['new']} new, "
        f"skipped {result['skipped']} unchanged, "
        f"removed {result['stale_removed']} stale "
        f"({result['errors']} errors)",
        file=sys.stderr,
    )
    print(f"  total: {result['total']} files at {result['db']}", file=sys.stderr)


def cmd_reindex(args):
    root = _resolve_root(args)
    p = db_path(root)
    if p.is_file():
        p.unlink()
    cmd_index(args)


def cmd_search(args):
    root = _resolve_root(args)
    results = do_search(root, args.query, top_k=args.top_k, language=args.lang)
    if args.json:
        print(json.dumps(results, indent=2))
        return
    if not results:
        print("(no results — run `index` first)", file=sys.stderr)
        return
    for r in results:
        print(f"  {r['score']:.3f}  {r['language']:<10} {r['path']}")
        print(f"           {r['sloc']} sloc, {r['bytes']} bytes, updated {r['updated_at']}")
        if r["snippet"]:
            first = r["snippet"].split("\n", 1)[0][:120]
            print(f"           {first}")


def cmd_stats(args):
    root = _resolve_root(args)
    s = do_stats(root)
    if not s.get("indexed"):
        print(f"kaizen-onboard: no index at {s['db_path']} — run `index` first")
        return
    print(f"db:        {s['db_path']}")
    print(f"root:      {s.get('root', '?')}")
    print(f"model:     {s.get('model', '?') or '?'}")
    print(f"dim:       {s.get('dim', '?') or '?'}")
    print(f"indexed:   {s.get('last_indexed_ts', '?') or '?'}")
    print(f"total:     {s['total']} files, {s['total_sloc']:,} sloc, {s['total_bytes']:,} bytes")
    for lang, n in s["by_language"].items():
        print(f"  {lang:<12} {n}")


def cmd_get(args):
    root = _resolve_root(args)
    r = do_get(root, args.id)
    if r is None:
        sys.exit(f"id {args.id} not found")
    print(json.dumps(r, indent=2))


def cmd_path(args):
    root = _resolve_root(args)
    print(db_path(root))


def cmd_clear(args):
    root = _resolve_root(args)
    p = db_path(root)
    if p.is_file():
        p.unlink()
        print(f"kaizen-onboard: cleared {p}", file=sys.stderr)
    else:
        print("kaizen-onboard: no index to clear", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-onboard-index",
        description="Semantic search over a codebase. Source files only, comments stripped, whitespace normalized.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="incremental index of source files")
    pi.add_argument("--root", help="project root (default: git toplevel or cwd)")
    pi.add_argument("--no-git", action="store_true", help="skip git ls-files; walk filesystem with ignore-list")
    pi.set_defaults(func=cmd_index)

    pr = sub.add_parser("reindex", help="wipe + full reindex")
    pr.add_argument("--root", help="project root")
    pr.add_argument("--no-git", action="store_true")
    pr.set_defaults(func=cmd_reindex)

    ps = sub.add_parser("search", help="semantic search")
    ps.add_argument("query")
    ps.add_argument("--top-k", type=int, default=10)
    ps.add_argument("--lang", help="filter by language (rust|python|typescript|...)")
    ps.add_argument("--root")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_search)

    pt = sub.add_parser("stats")
    pt.add_argument("--root")
    pt.set_defaults(func=cmd_stats)

    pg = sub.add_parser("get")
    pg.add_argument("id", type=int)
    pg.add_argument("--root")
    pg.set_defaults(func=cmd_get)

    pp = sub.add_parser("path")
    pp.add_argument("--root")
    pp.set_defaults(func=cmd_path)

    pc = sub.add_parser("clear")
    pc.add_argument("--root")
    pc.set_defaults(func=cmd_clear)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
