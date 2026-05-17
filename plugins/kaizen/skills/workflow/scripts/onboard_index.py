#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "sentence-transformers>=2.7",
#     "numpy>=1.24",
#     "torch>=2.0",
#     "sqlite-vec>=0.1.6",
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


# M1 — shared base in _sqlite.py. onboard is the only indexer that runs
# performance PRAGMAs (WAL, synchronous=NORMAL, cache_size, mmap, temp_store,
# foreign_keys) on every open; the others pass an empty `pragmas=""`.
import _sqlite as _kz_sqlite  # noqa: E402
import onboard_schema  # noqa: E402

# v1.31.0+ performance pragmas. WAL gives concurrent reader+writer;
# synchronous=NORMAL is safe with WAL; 64MB page cache + 256MB
# mmap region cover the entire onboard.db at shodan-scale (~50MB)
# with room to grow. temp_store=MEMORY keeps FTS5 merges in RAM.
_PRAGMAS_SQL = """
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA cache_size = -65536;
    PRAGMA mmap_size = 268435456;
    PRAGMA temp_store = MEMORY;
    PRAGMA foreign_keys = ON;
"""


# ─── DB schema + migrations live in onboard_schema.py ────────────────


def _populate_xref_imports(
    conn: sqlite3.Connection,
    file_id: int,
    cleaned_rec: dict,
    kept_chunks: list[dict],
) -> None:
    """O6 helper — populate code_chunks_xref with import bindings for
    Python source. No-op for other languages (extractor returns []).

    Each `import X` / `from M import Y` produces one xref row with
    kind='import'. The row is tied to the chunk_id of the file's
    module-level prologue chunk (kind='code', symbol_name='<module>').
    When no such chunk exists (e.g. file starts with a class/function),
    falls back to the file's first chunk."""
    if cleaned_rec.get("language") != "python":
        return
    raw_text = cleaned_rec.get("text") or cleaned_rec.get("cleaned") or ""
    if not raw_text:
        return
    try:
        from _ast_chunk import extract_python_imports as _eli
        imports = _eli(raw_text)
    except (ImportError, AttributeError):
        return
    if not imports:
        return

    # Find the chunk to hang imports on. Prefer the module prologue;
    # else the first chunk.
    target_chunk_idx = None
    for c in kept_chunks:
        if c.get("symbol_name") == "<module>":
            target_chunk_idx = c["chunk_idx"]
            break
    if target_chunk_idx is None and kept_chunks:
        target_chunk_idx = kept_chunks[0]["chunk_idx"]
    if target_chunk_idx is None:
        return

    row = conn.execute(
        "SELECT id FROM code_chunks WHERE file_id = ? AND chunk_idx = ?",
        (file_id, target_chunk_idx),
    ).fetchone()
    if not row:
        return
    chunk_id = row["id"]

    conn.executemany(
        """INSERT OR IGNORE INTO code_chunks_xref (chunk_id, symbol, kind)
           VALUES (?, ?, ?)""",
        [(chunk_id, imp.symbol, "import") for imp in imports],
    )


def open_db(root: Path, create: bool = True) -> sqlite3.Connection:
    conn = _kz_sqlite.open_indexer_db(
        db_path(root), onboard_schema.SCHEMA_SQL,
        pragmas=_PRAGMAS_SQL, create=create,
    )
    if create:
        # Migrations (idempotent): bring older dbs up to current schema.
        onboard_schema.apply_migrations(conn)
        # FTS5 mirror (separate from the SCHEMA_SQL executescript because
        # it uses triggers; _sqlite.open_indexer_db is schema-only).
        _kz_search.ensure_fts_mirror(conn, "code_chunks")
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    _kz_sqlite.set_meta(conn, "code_meta", key, value)


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    return _kz_sqlite.get_meta(conn, "code_meta", key, default)


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


# ─── Docstring extraction (O1: sidecar signal for "why" queries) ─────


_RUST_DOC = re.compile(r"^\s*///([^\n]*)", re.MULTILINE)
_RUST_INNER_DOC = re.compile(r"^\s*//!([^\n]*)", re.MULTILINE)
_JSDOC_BLOCK = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
_PY_TRIPLE_DOUBLE_CAPTURE = re.compile(r'"""(.*?)"""', re.DOTALL)
_PY_TRIPLE_SINGLE_CAPTURE = re.compile(r"'''(.*?)'''", re.DOTALL)
_C_DOC_LINE = re.compile(r"^\s*//[/!]([^\n]*)", re.MULTILINE)


def _clean_jsdoc_lines(block: str) -> str:
    """JSDoc /** lines often start with ` * `. Strip the leading-star
    bullets so the resulting prose embeds cleanly."""
    out = []
    for raw in block.split("\n"):
        s = raw.strip()
        if s.startswith("*"):
            s = s[1:].lstrip()
        if s:
            out.append(s)
    return "\n".join(out)


def _extract_python_docstrings(source: str) -> str:
    """AST-based for accuracy: pull module/class/function docstrings.
    Falls back to regex on SyntaxError so partial files still contribute."""
    try:
        import ast as _ast  # local import to keep top-level optional
        tree = _ast.parse(source)
    except (SyntaxError, ValueError):
        # Regex fallback — captures every triple-quoted block (incl.
        # those that aren't actually docstrings; OK for semantic search).
        parts: list[str] = []
        parts.extend(m.group(1).strip() for m in _PY_TRIPLE_DOUBLE_CAPTURE.finditer(source))
        parts.extend(m.group(1).strip() for m in _PY_TRIPLE_SINGLE_CAPTURE.finditer(source))
        return "\n\n".join(p for p in parts if p)
    parts: list[str] = []
    mod_doc = _ast.get_docstring(tree)
    if mod_doc:
        parts.append(mod_doc.strip())
    for node in _ast.walk(tree):
        if isinstance(
            node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)
        ):
            d = _ast.get_docstring(node)
            if d:
                parts.append(d.strip())
    return "\n\n".join(parts)


def _extract_rust_docstrings(source: str) -> str:
    """Concatenate `///` outer-doc + `//!` inner-doc comments."""
    parts = [m.group(1).strip() for m in _RUST_DOC.finditer(source)]
    parts.extend(m.group(1).strip() for m in _RUST_INNER_DOC.finditer(source))
    return "\n".join(p for p in parts if p)


def _extract_jsdoc(source: str) -> str:
    """Pull every JSDoc-style /** ... */ block and clean leading stars."""
    out = []
    for m in _JSDOC_BLOCK.finditer(source):
        cleaned = _clean_jsdoc_lines(m.group(1))
        if cleaned.strip():
            out.append(cleaned)
    return "\n\n".join(out)


def _extract_c_family_doc_lines(source: str) -> str:
    """C/C++/Java/Kotlin/Go-style `///` and `//!` doc lines (less common
    but used in Rust and some C++ codebases)."""
    parts = [m.group(1).strip() for m in _C_DOC_LINE.finditer(source)]
    return "\n".join(p for p in parts if p)


# Language → docstring-extractor registry. `c-family` extracts JSDoc
# blocks + doc lines; languages without a canonical docstring shape
# return empty.
_DOCSTRING_EXTRACTORS = {
    "python": _extract_python_docstrings,
    "rust": _extract_rust_docstrings,
    "c-family": lambda s: "\n\n".join(
        filter(None, [_extract_jsdoc(s), _extract_c_family_doc_lines(s)])
    ),
    "c-family-and-hash": _extract_jsdoc,  # JSX/TSX/etc.
}


def extract_docstrings(source: str, language: str) -> str:
    """Return the concatenated docstrings/header-comments for `source`.

    Empty string for languages without a canonical docstring convention
    (markdown, yaml, toml, sql, shell, etc.) — those use prose / values
    directly and don't need a sidecar signal.

    `language` is the canonical name from LANG_TABLE (e.g. 'python',
    'rust', 'typescript'). The function maps to the language's strategy
    (the same mapping used by strip_comments) to pick an extractor.
    """
    if not source:
        return ""
    strategy = _strategy_for_language(language)
    fn = _DOCSTRING_EXTRACTORS.get(strategy)
    return fn(source) if fn else ""


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


def _rel_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def read_raw_file(path: Path, root: Path) -> dict:
    """Stage 1 — lossless capture. Always returns a dict; on failure the
    record carries an `error` field (read or decode failure) and omits
    `text`/`sha`/etc. so the row is still queryable in `code_files_raw`."""
    rel = _rel_path(path, root)
    ext = path.suffix.lower()
    language = LANG_TABLE.get(ext, ("unknown", ""))[0]
    try:
        raw_bytes = path.read_bytes()
    except OSError as e:
        return {"path": rel, "language": language, "error": f"read failed: {e.__class__.__name__}: {e}"}
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        return {
            "path": rel,
            "language": language,
            "bytes": len(raw_bytes),
            "error": f"utf-8 decode failed at offset {e.start}: {e.reason}",
        }
    try:
        mtime = dt.datetime.fromtimestamp(
            path.stat().st_mtime, dt.timezone.utc
        ).isoformat()
    except OSError:
        mtime = ""
    return {
        "path": rel,
        "language": language,
        "bytes": len(raw_bytes),
        "sloc_raw": sum(1 for line in raw_text.split("\n") if line.strip()),
        "mtime": mtime,
        "text": raw_text,
        "sha": _file_sha(raw_bytes),
    }


def _strategy_for_language(language: str) -> str:
    for _ext, (lang, strat) in LANG_TABLE.items():
        if lang == language:
            return strat
    return "c-family"


def clean_for_embed(raw_rec: dict) -> dict:
    """Stage 2a — comment-strip + whitespace-normalize. Error rows pass
    through unchanged (preserved into the chunk stage so they keep
    surfacing in stats).

    O1: also extract docstrings as a SIDECAR signal so "why does X exist"
    queries match prose, not just code identifiers. Stored on the record
    under `docstrings` — chunk_record then emits doc-chunks alongside
    code-chunks.

    O5 (v1.34+): the file snippet is no longer the first 2 KB of
    cleaned text. ``_summary.smart_summary`` builds a dense signature
    + docstring summary (Python ast / tree-sitter) with the same byte
    budget. Falls back to first-2KB-cleaned when neither structural
    summary is available."""
    if raw_rec.get("error") or "text" not in raw_rec:
        return dict(raw_rec)
    language = raw_rec.get("language", "")
    strategy = _strategy_for_language(language)
    cleaned = normalize_whitespace(strip_comments(raw_rec["text"], strategy))
    docstrings = extract_docstrings(raw_rec["text"], language)
    out = dict(raw_rec)
    out["cleaned"] = cleaned
    out["docstrings"] = docstrings
    out["snippet"] = _kz_summary.smart_summary(
        raw_rec["text"], language, cleaned, max_chars=SNIPPET_MAX,
    )
    out["sloc"] = count_sloc(cleaned)
    return out


def chunk_record(cleaned_rec: dict) -> list[dict]:
    """Stage 2b — split a cleaned record into per-chunk records. Returns
    one dropped row (`kept: False`) for empty-after-clean files or error
    rows so do_filter can surface them in stats without losing them."""
    if cleaned_rec.get("error"):
        return [{
            "path": cleaned_rec["path"],
            "sha": cleaned_rec.get("sha"),
            "language": cleaned_rec.get("language"),
            "kept": False,
            "kept_reason": "raw_error",
            "error": cleaned_rec["error"],
        }]
    cleaned = cleaned_rec.get("cleaned", "")
    if not cleaned.strip():
        return [{
            "path": cleaned_rec["path"],
            "sha": cleaned_rec.get("sha"),
            "language": cleaned_rec.get("language"),
            "kept": False,
            "kept_reason": "empty_after_clean",
        }]
    # O2 (v1.33) / O8 (v1.34): symbol-aware chunking. Python uses
    # stdlib ast; everything else routes through tree-sitter (O8) when
    # available. Both fall back to the generic sentence-boundary
    # chunker on empty return.
    out: list[dict] = []
    language = cleaned_rec.get("language", "")
    raw_text = cleaned_rec.get("text") or cleaned
    if language == "python":
        sym_chunks = _kz_ast.chunk_python_by_symbol(raw_text)
    elif language:
        # O8: tree-sitter universal chunker for non-Python languages.
        # Returns [] when tree_sitter_languages isn't installed →
        # falls through to the sentence-boundary chunker below. Same
        # graceful-fallback shape as the Python path.
        ts_chunks = _kz_ts.chunk_source_by_symbol(raw_text, language)
        sym_chunks = ts_chunks
    else:
        sym_chunks = []
    if sym_chunks:
        for sc in sym_chunks:
            out.append({
                "path": cleaned_rec["path"],
                "sha": cleaned_rec.get("sha"),
                "language": language,
                "chunk_idx": sc.chunk_idx,
                "char_start": sc.char_start,
                "char_end": sc.char_end,
                "text": sc.text,
                "kind": "code",
                "symbol_name": sc.symbol_name,
                "kept": True,
            })
    if not out:
        # Non-Python OR Python that failed to parse — fall through to the
        # generic chunker. Same shape, symbol_name='' (sentinel for "not
        # ast-chunked").
        chunks = _kz_chunk.chunk_text(cleaned)
        for c in chunks:
            out.append({
                "path": cleaned_rec["path"],
                "sha": cleaned_rec.get("sha"),
                "language": language,
                "chunk_idx": c.chunk_idx,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "text": c.text,
                "kind": "code",
                "symbol_name": "",
                "kept": True,
            })
    # O1: emit doc-chunks alongside code-chunks. They share file_id but
    # carry kind="doc" so search can prefer doc results for "why" queries.
    # Doc chunks are NOT comment-stripped; the docstring text IS the signal.
    docstrings = (cleaned_rec.get("docstrings") or "").strip()
    if docstrings:
        doc_chunks = _kz_chunk.chunk_text(docstrings)
        next_idx = len(out)
        for c in doc_chunks:
            out.append({
                "path": cleaned_rec["path"],
                "sha": cleaned_rec.get("sha"),
                "language": cleaned_rec.get("language"),
                "chunk_idx": next_idx + c.chunk_idx,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "text": c.text,
                "kind": "doc",
                "symbol_name": "",
                "kept": True,
            })
    if not out:
        return [{
            "path": cleaned_rec["path"],
            "sha": cleaned_rec.get("sha"),
            "language": cleaned_rec.get("language"),
            "kept": False,
            "kept_reason": "no_chunks_produced",
        }]
    return out


def process_file(path: Path, root: Path) -> dict | None:
    """Back-compat wrapper around read_raw_file + clean_for_embed.

    Returns the legacy dict shape (`cleaned_for_embed`, `updated_at`,
    etc.) or None on error — preserved so callers outside this module
    keep working. New code should call the stage functions directly."""
    raw = read_raw_file(path, root)
    if raw.get("error"):
        return None
    cleaned = clean_for_embed(raw)
    return {
        "path": cleaned["path"],
        "language": cleaned["language"],
        "bytes": cleaned["bytes"],
        "sloc": cleaned["sloc"],
        "snippet": cleaned["snippet"],
        "cleaned_for_embed": cleaned["cleaned"],
        "sha": cleaned["sha"],
        "updated_at": cleaned.get("mtime", ""),
    }


import _embed as _kz_embed  # v1.25.0+: HTTP-first embedding backend
import _chunk as _kz_chunk  # v1.27.0+: sentence-boundary chunker
import _ast_chunk as _kz_ast  # v1.33.0+: symbol-aware Python chunker (O2)
import _ts_chunk as _kz_ts  # v1.34.0+: tree-sitter universal chunker (O8)
import _search as _kz_search  # v1.27.0+: BM25+dense hybrid search
import _quant as _kz_quant  # v1.31.0+: int8 quantization helpers
import _sparse as _kz_sparse  # v1.34.0+: SPLADE sparse-embedding helpers (E9)
import _colbert as _kz_colbert  # v1.34.0+: ColBERT late-interaction helpers (E10)
import _summary as _kz_summary  # v1.34.0+: smart file-level summary (O5)


def _has_embedding_q8_column(conn: sqlite3.Connection) -> bool:
    """Pre-v1.31 dbs lack `embedding_q8`. Cheap probe via PRAGMA so we
    can write quantized blobs only when the column exists."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
    return "embedding_q8" in cols


def _maybe_quantize_batch(
    conn: sqlite3.Connection, chunk_blobs: list[bytes], dim: int
) -> list[bytes] | None:
    """Return per-row int8 blobs when the embedding_q8 column exists
    AND numpy is importable; else None. Lazy + side-effect-free: dbs
    that haven't been migrated (or environments without numpy — the
    test harness running under bare python3) keep getting float32-only
    writes. A later `clear` + reindex under uv backfills the q8 column."""
    if not _has_embedding_q8_column(conn):
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    mat = np.stack([np.frombuffer(b, dtype=np.float32) for b in chunk_blobs])
    blobs, _ = _kz_quant.quantize_batch(mat)
    return blobs


def _has_embedding_sparse_column(conn: sqlite3.Connection) -> bool:
    """Pre-v1.34 dbs lack `embedding_sparse`. PRAGMA-probe so we only
    write sparse blobs when the column exists."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_chunks)")}
    return "embedding_sparse" in cols


def _maybe_sparse_batch(
    conn: sqlite3.Connection, texts: list[str]
) -> list[bytes | None] | None:
    """E9 — return per-row JSON-encoded sparse blobs when:

      1. `embedding_sparse` column exists (migration applied), AND
      2. `KAIZEN_SPARSE_ENABLE=1` is set, AND
      3. `_sparse.is_available()` reports True (transformers + torch +
         SPLADE model load cleanly).

    Returns `None` when sparse is disabled or unavailable (caller
    falls through to the non-sparse INSERT branch). Returns a list of
    `bytes | None` (same length as `texts`) otherwise — per-row None
    means the encoder produced nothing for that text (empty input)."""
    if not _has_embedding_sparse_column(conn):
        return None
    if not _kz_sparse.is_sparse_enabled():
        return None
    if not _kz_sparse.is_available():
        return None
    sparses = _kz_sparse.encode_sparse_batch(texts)
    return [_kz_sparse.serialize(s) if s else None for s in sparses]


def _maybe_colbert_batch(
    conn: sqlite3.Connection, texts: list[str]
) -> list[tuple[bytes, int, int] | None] | None:
    """E10 — return per-row (blob, seq_len, dim) tuples when:

      1. `code_chunks_colbert` sidecar table exists, AND
      2. `KAIZEN_COLBERT_ENABLE=1` is set, AND
      3. `_colbert.is_available()` reports True.

    Returns ``None`` when ColBERT is disabled / unavailable (caller
    skips the sidecar write). Returns a list (same length as ``texts``)
    of tuples or ``None`` per row otherwise — per-row ``None`` means
    the encoder produced an empty/invalid matrix for that text and the
    sidecar row should be skipped."""
    # Sidecar table is created at migration time; probe via sqlite_master
    # to avoid coupling to schema knowledge here.
    has_sidecar = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='code_chunks_colbert'"
    ).fetchone() is not None
    if not has_sidecar:
        return None
    if not _kz_colbert.is_colbert_enabled():
        return None
    if not _kz_colbert.is_available():
        return None
    mats = _kz_colbert.encode_colbert_batch(texts)
    out: list[tuple[bytes, int, int] | None] = []
    for mat in mats:
        if mat is None or getattr(mat, "size", 0) == 0:
            out.append(None)
            continue
        try:
            blob = _kz_colbert.serialize(mat)
            seq_len, dim = int(mat.shape[0]), int(mat.shape[1])
        except (ValueError, AttributeError, IndexError):
            out.append(None)
            continue
        out.append((blob, seq_len, dim))
    return out
from _progress import Progress as _Progress  # v1.30.0+: live stderr progress


def embed_one(text: str):
    # v1.25.0+: routes via _embed (llama-server HTTP first, sentence-transformers fallback).
    blob, _dim = _kz_embed.embed_one(text)
    return blob


# ─── do_* helpers (data-returning; mirrored by onboard_mcp.py) ───────


def do_dump(root: Path, use_git: bool = True) -> dict:
    """Stage 1 — lossless capture into `code_files_raw`.

    Walks the source tree, calls `read_raw_file` per file, INSERT OR
    REPLACEs into the raw table. Errors are stored as rows (text=NULL,
    error=<reason>) so `SELECT path, error FROM code_files_raw WHERE
    error IS NOT NULL` surfaces every failure with a concrete reason
    — fixes the pre-v1.31 "3 errors but no details" debuggability gap.

    Returns {total, captured, errors, db}.
    """
    conn = open_db(root, create=True)
    all_files = list(iter_source_files(root, use_git=use_git))
    bar = _Progress("onboard-dump", total=len(all_files))
    captured = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for path in all_files:
        rec = read_raw_file(path, root)
        is_err = bool(rec.get("error"))
        conn.execute(
            """INSERT OR REPLACE INTO code_files_raw
               (path, sha, language, bytes, sloc_raw, mtime, text, error, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.get("path"),
                rec.get("sha"),
                rec.get("language"),
                rec.get("bytes"),
                rec.get("sloc_raw"),
                rec.get("mtime"),
                rec.get("text"),
                rec.get("error"),
                now,
            ),
        )
        if is_err:
            errors += 1
            bar.tick(f"err {rec.get('path')}: {rec.get('error', '')[:60]}")
        else:
            captured += 1
            bar.tick(f"+ {rec['path']} ({rec.get('bytes', 0)}b)")
    set_meta(conn, "last_dump_ts", now)
    conn.commit()
    conn.close()
    bar.done(f"{captured} captured, {errors} errors")
    return {
        "total": len(all_files),
        "captured": captured,
        "errors": errors,
        "db": str(db_path(root)),
    }


def _skip_reason(conn: sqlite3.Connection, raw_rec: dict) -> str | None:
    """Incremental-skip predicate for do_filter's per-row loop.

    Returns 'error' for capture-failure rows (raw_rec.error set),
    'unchanged' when the path is already indexed at the same sha
    (incremental re-run), or None when the row needs (re-)processing.
    """
    if raw_rec.get("error"):
        return "error"
    # Skip rows whose sha matches an already-indexed file_row (incremental path).
    existing = conn.execute(
        "SELECT sha FROM code_files WHERE path = ?", (raw_rec["path"],)
    ).fetchone()
    if existing and existing["sha"] == raw_rec.get("sha"):
        return "unchanged"
    return None


def _build_chunk_payload(conn: sqlite3.Connection, raw_rec: dict) -> dict:
    """Computation half of do_filter — clean -> chunk -> embed for one raw row.

    Does no row writes; the only DB touch is the column-existence probes
    inside the _maybe_* helpers (which gate the optional q8/sparse/colbert
    representations against the db's migration tier). Returns a payload
    dict consumed by `_persist_file_and_chunks`. When the file produced no
    kept chunks, `kept` is [] and `drop_reason` carries why — the caller
    drops it without persisting.
    """
    cleaned_rec = clean_for_embed(raw_rec)
    chunk_records = chunk_record(cleaned_rec)
    kept = [c for c in chunk_records if c.get("kept")]
    if not kept:
        reason = chunk_records[0].get("kept_reason", "?") if chunk_records else "?"
        return {"cleaned_rec": cleaned_rec, "kept": [], "drop_reason": reason}
    # Embed all kept chunks in a single batch.
    # O3: metadata-rich passage prefix. Each chunk's embedded form
    # carries file/language/kind provenance so the model learns same-
    # file recall + kind discrimination. Original `text` in the DB is
    # unchanged — only the embedded representation differs.
    chunk_texts = _kz_chunk.apply_passage_prefix_batch_with_metadata(kept)
    chunk_blobs, _dim = _kz_embed.embed_batch(chunk_texts)
    # v1.31.0+: also compute the int8-quantized form for storage-efficient
    # search paths. `_quant.quantize_batch` returns one blob per row
    # (4-byte scale + D-byte int8 array). Lazy: only computes when the
    # embedding_q8 column exists (back-compat with pre-v1.31 dbs).
    chunk_q8_blobs = _maybe_quantize_batch(conn, chunk_blobs, _dim)
    # E9 (v1.34+): also compute SPLADE sparse vectors when
    # KAIZEN_SPARSE_ENABLE=1 AND transformers/torch are available.
    # `_maybe_sparse_batch` returns None when sparse is disabled →
    # the persister skips the sparse column entirely (same back-compat
    # shape as the q8 branch for pre-v1.31 dbs).
    chunk_sparse_blobs = _maybe_sparse_batch(conn, chunk_texts)
    # E10 (v1.34+): also compute the ColBERT multi-vector sidecar when
    # KAIZEN_COLBERT_ENABLE=1. Returns None when disabled; else a list
    # of (blob, seq_len, dim) tuples or None per row.
    chunk_colbert_payloads = _maybe_colbert_batch(conn, chunk_texts)
    return {
        "cleaned_rec": cleaned_rec,
        "kept": kept,
        "drop_reason": "",
        "chunk_blobs": chunk_blobs,
        "chunk_q8_blobs": chunk_q8_blobs,
        "chunk_sparse_blobs": chunk_sparse_blobs,
        "chunk_colbert_payloads": chunk_colbert_payloads,
    }


def _persist_file_and_chunks(conn: sqlite3.Connection, payload: dict) -> int:
    """Persistence half of do_filter — write one file row + its chunk rows
    from a `_build_chunk_payload` result. Owns the dynamic-column INSERT
    (`embedding_q8` / `embedding_sparse` are optional columns whose
    presence depends on the db's migration tier). Returns the chunk count.
    """
    cleaned_rec = payload["cleaned_rec"]
    kept = payload["kept"]
    chunk_blobs = payload["chunk_blobs"]
    chunk_q8_blobs = payload["chunk_q8_blobs"]
    chunk_sparse_blobs = payload["chunk_sparse_blobs"]
    chunk_colbert_payloads = payload["chunk_colbert_payloads"]
    file_emb = chunk_blobs[0]
    # Upsert the file row.
    conn.execute(
        """INSERT OR REPLACE INTO code_files
           (path, language, bytes, sloc, snippet, embedding, sha, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cleaned_rec["path"],
            cleaned_rec["language"],
            cleaned_rec["bytes"],
            cleaned_rec["sloc"],
            cleaned_rec["snippet"],
            file_emb,
            cleaned_rec["sha"],
            cleaned_rec.get("mtime", ""),
        ),
    )
    file_id = conn.execute(
        "SELECT id FROM code_files WHERE path = ?", (cleaned_rec["path"],)
    ).fetchone()["id"]
    conn.execute("DELETE FROM code_chunks WHERE file_id = ?", (file_id,))
    # NB: chunk_id cascades into code_chunks_xref via FK ON DELETE CASCADE
    # Build the INSERT dynamically: `embedding_q8` and `embedding_sparse`
    # are optional columns that may or may not exist depending on the
    # db's migration tier (pre-v1.31 lacks q8; pre-v1.34 lacks sparse).
    # Always-present columns first, then optional columns appended
    # only when the helper returned a non-None list.
    cols: list[str] = [
        "file_id", "chunk_idx", "char_start", "char_end",
        "text", "embedding",
    ]
    if chunk_q8_blobs is not None:
        cols.append("embedding_q8")
    cols.extend(["language", "kind", "symbol_name"])
    if chunk_sparse_blobs is not None:
        cols.append("embedding_sparse")
    sql = (
        f"INSERT INTO code_chunks ({','.join(cols)}) "
        f"VALUES ({','.join('?' for _ in cols)})"
    )
    rows: list[tuple] = []
    for idx, c in enumerate(kept):
        row: list = [
            file_id, c["chunk_idx"], c["char_start"], c["char_end"],
            c["text"], chunk_blobs[idx],
        ]
        if chunk_q8_blobs is not None:
            row.append(chunk_q8_blobs[idx])
        row.extend([
            cleaned_rec["language"],
            c.get("kind") or "code",
            c.get("symbol_name") or "",
        ])
        if chunk_sparse_blobs is not None:
            row.append(chunk_sparse_blobs[idx])
        rows.append(tuple(row))
    conn.executemany(sql, rows)
    # O6 (v1.33): populate code_chunks_xref from Python imports. Each
    # imported symbol becomes one xref row tied to whichever chunk
    # contains the source `import` statement. Heuristic: the module-
    # level prologue chunk (kind='code', symbol_name='<module>') owns
    # them. Other languages skip (extractor returns []).
    _populate_xref_imports(conn, file_id, cleaned_rec, kept)
    # E10 (v1.34): ColBERT multi-vector sidecar. Re-query chunk_ids
    # by (file_id, chunk_idx) because executemany doesn't expose them.
    # Only runs when KAIZEN_COLBERT_ENABLE=1 + colbert available.
    if chunk_colbert_payloads is not None:
        id_rows = conn.execute(
            "SELECT id, chunk_idx FROM code_chunks "
            "WHERE file_id = ? ORDER BY chunk_idx",
            (file_id,),
        ).fetchall()
        idx_to_id = {int(r["chunk_idx"]): int(r["id"]) for r in id_rows}
        sidecar_rows = []
        for i, c in enumerate(kept):
            colbert_payload = chunk_colbert_payloads[i]
            if colbert_payload is None:
                continue
            chunk_id = idx_to_id.get(c["chunk_idx"])
            if chunk_id is None:
                continue
            blob, seq_len, dim = colbert_payload
            sidecar_rows.append((chunk_id, blob, seq_len, dim))
        if sidecar_rows:
            # INSERT OR REPLACE — the DELETE FROM code_chunks above
            # cascaded into code_chunks_colbert via FK, so this is
            # really just INSERT. OR REPLACE guards against any
            # racy partial-state leftover.
            conn.executemany(
                """INSERT OR REPLACE INTO code_chunks_colbert
                   (chunk_id, vectors, seq_len, dim)
                   VALUES (?, ?, ?, ?)""",
                sidecar_rows,
            )
    return len(kept)


def _finalize_filter(
    conn: sqlite3.Connection, root: Path, seen_paths: set[str]
) -> int:
    """Closing half of do_filter — drop stale rows, refresh meta, compact.

    Removes code_files rows whose path is no longer in the raw table
    (the raw table is the source of truth for what exists on disk),
    refreshes the code_meta counters, commits, and runs the FTS5 +
    query-planner optimize pass. Returns the stale-removed count.
    """
    # Remove stale entries (in db but not in raw table). The raw table
    # is the source of truth for what currently exists on disk.
    all_in_db = conn.execute("SELECT path FROM code_files").fetchall()
    stale = [r["path"] for r in all_in_db if r["path"] not in seen_paths]
    for p in stale:
        row = conn.execute("SELECT id FROM code_files WHERE path = ?", (p,)).fetchone()
        if row:
            conn.execute("DELETE FROM code_chunks WHERE file_id = ?", (row["id"],))
            conn.execute("DELETE FROM code_files WHERE path = ?", (p,))
    set_meta(conn, "model", DEFAULT_MODEL)
    set_meta(conn, "dim", str(DEFAULT_DIM))
    set_meta(conn, "last_indexed_ts", dt.datetime.now(dt.timezone.utc).isoformat())
    set_meta(conn, "total_files", str(
        conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
    ))
    set_meta(conn, "total_chunks", str(
        conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
    ))
    set_meta(conn, "root", str(root))
    conn.commit()
    # v1.31.0+: compact the index after every filter run.
    # `PRAGMA optimize` updates query-planner statistics; FTS5
    # `optimize` merges segments into one B-tree (large recall win on
    # the BM25 path; recall already correct, but the merged form
    # answers queries in fewer page reads).
    try:
        conn.executescript(
            """
            INSERT INTO code_chunks_fts(code_chunks_fts) VALUES('optimize');
            PRAGMA optimize;
            """
        )
        conn.commit()
    except sqlite3.OperationalError:
        # FTS5 mirror absent (pre-v1.28 db): skip.
        pass
    return len(stale)


def do_filter(root: Path) -> dict:
    """Stage 2 — clean + chunk + embed from `code_files_raw` into
    `code_files` + `code_chunks`.

    Does NOT touch the filesystem. The raw table is the single source
    of truth for "what we saw on disk" — re-running this stage after a
    new comment-strip rule lands re-uses captured text. Error rows
    (raw_rec.error IS NOT NULL) are counted into `errors_skipped` and
    excluded from the chunked tables.

    Thin coordinator: per raw row it consults `_skip_reason`, builds the
    chunk payload via `_build_chunk_payload`, and writes it with
    `_persist_file_and_chunks`; `_finalize_filter` closes out stale rows,
    meta, and the compaction pass.

    Returns {files_indexed, chunks, errors_skipped, dropped,
    stale_removed, db}.
    """
    conn = open_db(root, create=True)
    raw_rows = conn.execute(
        "SELECT path, sha, language, bytes, sloc_raw, mtime, text, error "
        "FROM code_files_raw ORDER BY path"
    ).fetchall()
    bar = _Progress("onboard-filter", total=len(raw_rows))
    seen_paths: set[str] = set()
    files_indexed = 0
    chunks_written = 0
    errors_skipped = 0
    dropped = 0
    for r in raw_rows:
        raw_rec = {k: r[k] for k in r.keys()}
        seen_paths.add(raw_rec["path"])
        skip = _skip_reason(conn, raw_rec)
        if skip == "error":
            errors_skipped += 1
            bar.tick(f"skip-err {raw_rec['path']}")
            continue
        if skip == "unchanged":
            bar.tick(f"skip-unchanged {raw_rec['path']}")
            continue
        payload = _build_chunk_payload(conn, raw_rec)
        if not payload["kept"]:
            dropped += 1
            bar.tick(f"drop {raw_rec['path']} ({payload['drop_reason']})")
            continue
        chunks_written += _persist_file_and_chunks(conn, payload)
        files_indexed += 1
        bar.tick(
            f"+ {payload['cleaned_rec']['path']} "
            f"({len(payload['kept'])} chunks)"
        )
    stale_removed = _finalize_filter(conn, root, seen_paths)
    conn.close()
    bar.done(
        f"{files_indexed} indexed, {chunks_written} chunks, "
        f"{errors_skipped} skipped, {dropped} dropped"
    )
    return {
        "files_indexed": files_indexed,
        "chunks": chunks_written,
        "errors_skipped": errors_skipped,
        "dropped": dropped,
        "stale_removed": stale_removed,
        "db": str(db_path(root)),
    }


def do_index(root: Path, use_git: bool = True) -> dict:
    """End-to-end incremental indexing — dump → filter (v1.31.0+).

    Stage 1 (`do_dump`) writes every source file's raw contents into
    `code_files_raw` (lossless; errors preserved as queryable rows).
    Stage 2 (`do_filter`) reads the raw table, applies clean + chunk +
    embed, writes into `code_files` + `code_chunks`. Re-running stage
    2 alone (e.g. after a comment-strip rule change) does NOT re-read
    the filesystem.

    Return shape preserved for back-compat with onboard_mcp.py and
    cmd_index/cmd_reindex output: {new, skipped, stale_removed, errors,
    total, total_chunks, new_chunks, model, db}.
    """
    dump = do_dump(root, use_git=use_git)
    filt = do_filter(root)
    total = dump["captured"] + dump["errors"]  # rows in code_files_raw
    return {
        "new": filt["files_indexed"],
        "skipped": dump["captured"] - filt["files_indexed"] - filt["dropped"],
        "stale_removed": filt["stale_removed"],
        "errors": dump["errors"] + filt["dropped"],
        "total": total,
        "total_chunks": filt["chunks"],
        "new_chunks": filt["chunks"],
        "model": DEFAULT_MODEL,
        "db": str(db_path(root)),
        # v1.31.0+ adds the per-stage breakdown for callers that want it.
        "dump": dump,
        "filter": filt,
    }


def do_search(
    root: Path,
    query: str,
    top_k: int = 10,
    language: str | None = None,
    *,
    alpha: float = 0.5,
    legacy: bool = False,
) -> list[dict]:
    """Search the index. Returns ranked file results with best-chunk citation.

    Two paths:
      - **default (chunked)** — BM25 + dense hybrid over `code_chunks`.
        Results carry `matched_chunk_idx` + `char_range` for citation.
      - **legacy=True** — cosine over `code_files.embedding` (whole-file
        match, pre-v1.28 behavior). Useful for very-coarse search or when
        chunks aren't populated (db indexed before v1.28.0).
    """
    path = db_path(root)
    if not path.is_file():
        return []
    conn = open_db(root, create=False)

    if legacy:
        return _do_search_legacy(conn, query, top_k=top_k, language=language)

    # Chunked path: hybrid_search returns [(chunk_id, score), ...].
    extra_where = "language = ?" if language else ""
    extra_params: list = [language] if language else []
    try:
        hits = _kz_search.hybrid_search(
            conn, "code_chunks", query, top_k=top_k,
            candidate_pool=max(top_k * 5, 50),
            alpha=alpha,
            extra_where=extra_where, extra_params=extra_params,
        )
    except sqlite3.OperationalError as e:
        # FTS table missing → db was indexed pre-v1.28. Fall back to legacy.
        sys.stderr.write(
            f"kaizen-onboard: chunked search unavailable ({e}); falling back to legacy.\n"
            "  Re-run `kaizen-onboard reindex` to enable hybrid search.\n"
        )
        return _do_search_legacy(conn, query, top_k=top_k, language=language)

    if not hits:
        conn.close()
        return []

    # Group by file: keep the best-scoring chunk per file (matches Onyx's
    # default "best chunk wins" answer-render path).
    best_per_file: dict[int, dict] = {}
    chunk_ids = [c for c, _ in hits]
    placeholders = ",".join("?" * len(chunk_ids))
    chunk_rows = conn.execute(
        f"""SELECT id, file_id, chunk_idx, char_start, char_end, text
            FROM code_chunks WHERE id IN ({placeholders})""",
        chunk_ids,
    ).fetchall()
    chunk_by_id = {r["id"]: r for r in chunk_rows}
    for cid, score in hits:
        cr = chunk_by_id.get(cid)
        if cr is None:
            continue
        fid = cr["file_id"]
        if fid not in best_per_file or score > best_per_file[fid]["score"]:
            best_per_file[fid] = {
                "score": score,
                "matched_chunk_idx": cr["chunk_idx"],
                "char_range": [cr["char_start"], cr["char_end"]],
                "matched_snippet": cr["text"][:500],
            }

    # Fetch file metadata in one query.
    file_ids = list(best_per_file.keys())
    placeholders = ",".join("?" * len(file_ids))
    file_rows = conn.execute(
        f"SELECT * FROM code_files WHERE id IN ({placeholders})", file_ids
    ).fetchall()
    out: list[dict] = []
    for fr in file_rows:
        info = best_per_file[fr["id"]]
        out.append({
            "score": round(info["score"], 4),
            "id": fr["id"],
            "path": fr["path"],
            "language": fr["language"],
            "bytes": fr["bytes"],
            "sloc": fr["sloc"],
            "matched_chunk_idx": info["matched_chunk_idx"],
            "char_range": info["char_range"],
            "snippet": info["matched_snippet"],
            "updated_at": fr["updated_at"],
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    conn.close()
    return out


def _do_search_legacy(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 10,
    language: str | None = None,
) -> list[dict]:
    """Pre-v1.28 whole-file cosine search. Used as fallback when chunks
    aren't populated, and via `--legacy`."""
    np = _kz_embed.require_numpy()
    qblob, _ = _kz_embed.embed_one(query)
    qvec = np.frombuffer(qblob, dtype=np.float32).astype(np.float32)
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)
    q_dim = qvec.shape[0]
    where_sql = ""
    params: list = []
    if language:
        where_sql = " WHERE language = ?"
        params.append(language)
    rows = conn.execute(
        f"SELECT * FROM code_files{where_sql}", params
    ).fetchall()
    scored = []
    skipped_mismatch = 0
    for r in rows:
        evec = np.frombuffer(r["embedding"], dtype=np.float32)
        if evec.shape[0] != q_dim:
            skipped_mismatch += 1
            continue
        score = float(np.dot(qnorm, evec / (np.linalg.norm(evec) + 1e-12)))
        scored.append((score, r))
    if skipped_mismatch:
        sys.stderr.write(
            f"kaizen-onboard: skipped {skipped_mismatch} row(s) with dim != {q_dim} — "
            f"reindex after embed-backend change\n"
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, r in scored[:top_k]:
        out.append({
            "score": round(score, 4),
            "id": r["id"],
            "path": r["path"],
            "language": r["language"],
            "bytes": r["bytes"],
            "sloc": r["sloc"],
            "snippet": r["snippet"],
            "updated_at": r["updated_at"],
        })
    conn.close()
    return out


def do_raw_errors(root: Path) -> list[dict]:
    """Stage-1 diagnostic — rows in `code_files_raw` where read or decode
    failed. Returns [{path, language, error, bytes}]; empty list if all
    files captured cleanly."""
    p = db_path(root)
    if not p.is_file():
        return []
    conn = open_db(root, create=False)
    rows = conn.execute(
        "SELECT path, language, error, bytes FROM code_files_raw "
        "WHERE error IS NOT NULL ORDER BY path"
    ).fetchall()
    conn.close()
    return [{k: r[k] for k in r.keys()} for r in rows]


def do_dropped(root: Path) -> list[dict]:
    """Stage-2 diagnostic — files present in `code_files_raw` but absent
    from `code_files` (chunker produced nothing kept). Common cause:
    file is 100% comments; comment-strip empties it. Returns
    [{path, language, bytes, sloc_raw, reason}]."""
    p = db_path(root)
    if not p.is_file():
        return []
    conn = open_db(root, create=False)
    rows = conn.execute(
        "SELECT r.path, r.language, r.bytes, r.sloc_raw "
        "FROM code_files_raw r LEFT JOIN code_files f ON f.path = r.path "
        "WHERE r.error IS NULL AND f.id IS NULL "
        "ORDER BY r.path"
    ).fetchall()
    conn.close()
    return [
        {**{k: r[k] for k in r.keys()}, "reason": "empty_after_clean_or_no_chunks"}
        for r in rows
    ]


def do_stats(root: Path) -> dict:
    path = db_path(root)
    if not path.is_file():
        return {"indexed": False, "db_path": str(path)}
    conn = open_db(root, create=False)
    total = conn.execute("SELECT COUNT(*) FROM code_files").fetchone()[0]
    # v1.28.0+: chunks table may not exist on pre-v1.28 dbs.
    try:
        total_chunks = conn.execute("SELECT COUNT(*) FROM code_chunks").fetchone()[0]
    except sqlite3.OperationalError:
        total_chunks = 0
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
        "total_chunks": total_chunks,
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
    results = do_search(
        root, args.query,
        top_k=args.top_k, language=args.lang,
        alpha=args.alpha, legacy=args.legacy,
    )
    if args.json:
        _emit(results, counts={"results": len(results)})
        return
    if not results:
        print("(no results — run `index` first)", file=sys.stderr)
        return
    for r in results:
        print(f"  {r['score']:.3f}  {r['language']:<10} {r['path']}")
        cite = ""
        if "char_range" in r:
            cite = f" [chunk {r['matched_chunk_idx']} chars {r['char_range'][0]}..{r['char_range'][1]}]"
        print(f"           {r['sloc']} sloc, {r['bytes']} bytes, updated {r['updated_at']}{cite}")
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
    chunks_str = f", {s['total_chunks']:,} chunks" if s.get("total_chunks") else " (pre-v1.28 db — `reindex` to enable hybrid search)"
    print(f"total:     {s['total']} files, {s['total_sloc']:,} sloc, {s['total_bytes']:,} bytes{chunks_str}")
    for lang, n in s["by_language"].items():
        print(f"  {lang:<12} {n}")


def cmd_get(args):
    root = _resolve_root(args)
    r = do_get(root, args.id)
    if r is None:
        sys.exit(f"id {args.id} not found")
    _emit(r)


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


def cmd_dump(args):
    """v1.31.0+: stage 1 only — populate code_files_raw with lossless capture."""
    root = _resolve_root(args)
    result = do_dump(root, use_git=not args.no_git)
    print(
        f"kaizen-onboard: dumped {result['captured']} captured, "
        f"{result['errors']} errors → {result['db']}",
        file=sys.stderr,
    )


def cmd_filter(args):
    """v1.31.0+: stage 2 only — clean + chunk + embed from code_files_raw.
    Re-runnable without re-reading the filesystem."""
    root = _resolve_root(args)
    result = do_filter(root)
    print(
        f"kaizen-onboard: filtered {result['files_indexed']} indexed, "
        f"{result['chunks']} chunks, {result['errors_skipped']} skipped, "
        f"{result['dropped']} dropped, {result['stale_removed']} stale removed",
        file=sys.stderr,
    )


def cmd_raw(args):
    """v1.31.0+: query the lossless capture table — list, show one, or
    surface errors. Useful when stats reports 'N errors' and you need
    the concrete failure reasons."""
    root = _resolve_root(args)
    conn = open_db(root, create=False)
    if args.errors:
        rows = conn.execute(
            "SELECT path, error FROM code_files_raw "
            "WHERE error IS NOT NULL ORDER BY path"
        ).fetchall()
        if not rows:
            print("kaizen-onboard: no errors in code_files_raw", file=sys.stderr)
            return
        for r in rows:
            print(f"  {r['path']}\t{r['error']}")
        return
    if args.show:
        row = conn.execute(
            "SELECT * FROM code_files_raw WHERE path = ?", (args.show,)
        ).fetchone()
        if not row:
            sys.exit(f"path not found in code_files_raw: {args.show}")
        d = {k: row[k] for k in row.keys()}
        # Truncate `text` in stdout for readability; full content via --full.
        if d.get("text") and not args.full:
            d["text"] = d["text"][:500] + ("…" if len(d["text"]) > 500 else "")
        _emit(d)
        return
    # Default: list paths + status (ok | error).
    rows = conn.execute(
        "SELECT path, language, bytes, sloc_raw, "
        "       CASE WHEN error IS NULL THEN 'ok' ELSE 'error' END AS status "
        "FROM code_files_raw ORDER BY path"
    ).fetchall()
    for r in rows:
        print(f"  {r['status']:<6} {r['language']:<10} {r['bytes']:>8}b  {r['path']}")
    print(f"  ({len(rows)} rows)", file=sys.stderr)


# ─── CLI (M7: thin IndexerCLI subclass) ──────────────────────────────


from _indexer_cli import IndexerCLI  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-onboard", tool_version="1.0.0")


class OnboardCLI(IndexerCLI):
    PROG = "kaizen-onboard-index"
    DESCRIPTION = (
        "Semantic search over a codebase. Source files only, comments "
        "stripped, whitespace normalized."
    )

    def db_path_for(self, args):
        return db_path(_resolve_root(args))

    # Existing module-level cmd_* already print; delegate to preserve
    # their human-facing output verbatim.
    def cmd_stats(self, args): cmd_stats(args)
    def cmd_get(self, args): cmd_get(args)
    def cmd_search(self, args): cmd_search(args)
    def cmd_index(self, args): cmd_index(args)
    def cmd_reindex(self, args): cmd_reindex(args)
    def cmd_path(self, args): cmd_path(args)
    def cmd_clear(self, args): cmd_clear(args)

    # do_* surface — wraps existing module helpers for IndexerCLI contract
    # (not used directly because each cmd_* override delegates to the
    # existing module-level cmd_* which itself calls the do_* helpers).
    def do_stats(self, args):
        return do_stats(_resolve_root(args))

    def do_get(self, args):
        return do_get(_resolve_root(args), args.id)

    def do_search(self, args):
        return do_search(
            _resolve_root(args), args.query,
            top_k=args.top_k, language=args.lang,
            alpha=args.alpha, legacy=args.legacy,
        )

    def do_index(self, args):
        return do_index(_resolve_root(args), use_git=not args.no_git)

    def do_reindex(self, args):
        root = _resolve_root(args)
        p = db_path(root)
        if p.is_file():
            p.unlink()
        return self.do_index(args)

    def extra_index_args(self, p):
        p.add_argument("--root",
                       help="project root (default: git toplevel or cwd)")
        p.add_argument("--no-git", action="store_true",
                       help="skip git ls-files; walk filesystem with "
                            "ignore-list")

    def extra_reindex_args(self, p):
        p.add_argument("--root", help="project root")
        p.add_argument("--no-git", action="store_true")

    def extra_search_args(self, p):
        p.add_argument("--lang",
                       help="filter by language (rust|python|typescript|...)")
        p.add_argument("--alpha", type=float, default=0.5,
                       help="hybrid weight: 1.0=dense only, 0.0=BM25 only, "
                            "0.5=balanced (default)")
        p.add_argument("--legacy", action="store_true",
                       help="use pre-v1.28 whole-file cosine instead of "
                            "chunked hybrid")
        p.add_argument("--root")

    def extra_stats_args(self, p): p.add_argument("--root")
    def extra_get_args(self, p): p.add_argument("--root")
    def extra_path_args(self, p): p.add_argument("--root")
    def extra_clear_args(self, p): p.add_argument("--root")

    def register_extra_subcommands(self, sub):
        # v1.31.0+: pipeline stages exposed individually.
        pd = sub.add_parser(
            "dump",
            help="stage 1 — capture raw file contents into "
                 "code_files_raw (lossless)",
        )
        pd.add_argument("--root")
        pd.add_argument("--no-git", action="store_true")
        pd.set_defaults(func=cmd_dump)

        pf = sub.add_parser(
            "filter",
            help="stage 2 — clean + chunk + embed from code_files_raw "
                 "(no fs read)",
        )
        pf.add_argument("--root")
        pf.set_defaults(func=cmd_filter)

        pw = sub.add_parser(
            "raw",
            help="inspect code_files_raw: list rows, show one, or "
                 "surface errors",
        )
        pw.add_argument("--root")
        pw.add_argument("--errors", action="store_true",
                        help="list rows where error IS NOT NULL")
        pw.add_argument("--show", metavar="PATH",
                        help="show the full raw row for one path "
                             "(text truncated)")
        pw.add_argument("--full", action="store_true",
                        help="when used with --show, emit full untruncated "
                             "text")
        pw.set_defaults(func=cmd_raw)


def build_parser() -> argparse.ArgumentParser:
    """Back-compat shim."""
    return OnboardCLI().build_parser()


def main():
    OnboardCLI().run()


if __name__ == "__main__":
    main()
