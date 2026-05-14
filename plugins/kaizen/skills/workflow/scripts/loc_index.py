#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""kaizen loc-index — function-level codebase metrics + per-symbol search.

Python port of shodan's `xtask/src/loc.rs` (commit 04af201). 100% accurate
function extraction via stdlib `ast` for `.py`; regex fallback for other
languages until tree-sitter is wired (X1 Phase 4).

Per-repo SQLite index at `<repo>/.kaizen/loc.db`. Parallels onboard.db.

## SQLite schema

    loc_symbols:
        id                  INTEGER PRIMARY KEY AUTOINCREMENT
        path                TEXT NOT NULL      -- relative to root
        language            TEXT NOT NULL      -- 'Python' | 'Rust' | ...
        symbol_kind         TEXT NOT NULL      -- function | method | class | ...
        symbol_name         TEXT NOT NULL
        qualified_name      TEXT NOT NULL      -- 'Mod.Class.method' / 'free_fn'
        parent_symbol       TEXT
        line_start          INTEGER NOT NULL   -- 1-indexed, inclusive
        line_end            INTEGER NOT NULL
        col_start           INTEGER
        col_end             INTEGER
        byte_start          INTEGER NOT NULL
        byte_end            INTEGER NOT NULL
        physical_lines      INTEGER NOT NULL
        logical_lines       INTEGER
        cyclomatic          INTEGER            -- McCabe (Python AST)
        cognitive           INTEGER            -- future (Sonar-style)
        nesting_depth       INTEGER
        has_docstring       INTEGER NOT NULL
        is_test             INTEGER NOT NULL
        is_async            INTEGER NOT NULL
        is_public           INTEGER NOT NULL   -- Python: not starting with '_'
        signature           TEXT
        signature_hash      TEXT
        body_sha            TEXT NOT NULL
        parser              TEXT NOT NULL      -- 'ast' | 'syn' | 'regex'
        updated_at          TEXT NOT NULL
        UNIQUE(path, line_start, symbol_name)

    loc_files:
        path                TEXT PRIMARY KEY
        language            TEXT NOT NULL
        physical_lines      INTEGER NOT NULL
        logical_lines       INTEGER NOT NULL
        comment_lines       INTEGER NOT NULL
        blank_lines         INTEGER NOT NULL
        symbol_count        INTEGER NOT NULL
        test_symbol_count   INTEGER NOT NULL
        god_tier            TEXT               -- 'critical' | 'warning' | NULL
        max_function_lines  INTEGER NOT NULL
        comment_density     REAL NOT NULL
        sha                 TEXT NOT NULL
        updated_at          TEXT NOT NULL

    loc_meta:
        key                 TEXT PRIMARY KEY
        value               TEXT

## Subcommands

    index [--root PATH]              incremental index (sha-deduped)
    reindex                          wipe + full rebuild
    search <filters>                 symbol search (--name / --at / --kind / etc.)
    files <filters>                  file search (--god / --comment-density / ...)
    show <id> [--json]               print symbol source by byte range
    stats [--by language|kind]       index stats
    report [--json]                  xtask-style verdict
    get <id>                         fetch one symbol record
    path                             print db path
    clear                            drop db

## Env

    KAIZEN_LOC_DB                    override db path (default <root>/.kaizen/loc.db)
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _sqlite as _kz_sqlite  # noqa: E402
from _indexer_cli import IndexerCLI  # noqa: E402


# ─── Language detection ──────────────────────────────────────────────


LANG_BY_EXT: dict[str, str] = {
    "py": "Python",
    "rs": "Rust",
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "js": "JavaScript",
    "jsx": "JavaScript",
    "mjs": "JavaScript",
    "cjs": "JavaScript",
    "go": "Go",
    "java": "Java",
    "kt": "Kotlin",
    "scala": "Scala",
    "swift": "Swift",
    "cs": "C#",
    "c": "C",
    "h": "C",
    "cpp": "C++",
    "cc": "C++",
    "cxx": "C++",
    "hpp": "C++",
    "rb": "Ruby",
    "php": "PHP",
    "lua": "Lua",
    "sh": "Shell",
    "bash": "Shell",
    "zsh": "Shell",
    "sql": "SQL",
    "md": "Markdown",
    "markdown": "Markdown",
    "html": "HTML",
    "htm": "HTML",
    "css": "CSS",
    "scss": "CSS",
    "sass": "CSS",
    "json": "JSON",
    "jsonl": "JSON",
    "jsonc": "JSON",
    "yaml": "YAML",
    "yml": "YAML",
    "toml": "TOML",
    "graphql": "GraphQL",
    "gql": "GraphQL",
    "vue": "Vue",
    "svelte": "Vue",
    "proto": "Protobuf",
}

IGNORE_DIRS = (
    "/.git/", "/.claude/", "/.kaizen/", "/.remember/", "/.vscode/",
    "/target/", "/node_modules/", "/vendor/", "/dist/", "/build/",
    "/.venv/", "/venv/", "/__pycache__/", "/.tox/", "/.pytest_cache/",
    "/.mypy_cache/", "/.ruff_cache/",
)

IGNORE_SUFFIXES = (
    ".min.js", ".min.css", ".d.ts", "Cargo.lock", "package-lock.json",
    "pnpm-lock.yaml", "uv.lock", "poetry.lock", ".snap", ".pem", ".crt",
    ".key", ".svg", ".png", ".jpg", ".jpeg", ".ico", ".gif", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".woff",
    ".woff2", ".ttf", ".otf", ".eot", ".pyc", ".pyo",
)

GOD_WARNING_LINES = 500
GOD_CRITICAL_LINES = 1000


# ─── Symbol record ───────────────────────────────────────────────────


@dataclass
class FunctionInfo:
    """One symbol record. Mirrors shodan loc.rs::FunctionInfo + the
    full X1 schema fields. Lines are 1-indexed inclusive."""

    path: str
    language: str
    symbol_kind: str          # function | method | class | async-function | ...
    symbol_name: str
    qualified_name: str
    parent_symbol: str | None = None
    line_start: int = 1
    line_end: int = 1
    col_start: int | None = None
    col_end: int | None = None
    byte_start: int = 0
    byte_end: int = 0
    physical_lines: int = 1
    logical_lines: int | None = None
    cyclomatic: int | None = None
    cognitive: int | None = None
    nesting_depth: int | None = None
    has_docstring: bool = False
    is_test: bool = False
    is_async: bool = False
    is_public: bool = True
    signature: str | None = None
    signature_hash: str | None = None
    body_sha: str = ""
    parser: str = "ast"

    def citation(self) -> str:
        """`<file>:<start>-<end>` — copy-pasteable into editors."""
        return f"{self.path}:{self.line_start}-{self.line_end}"


# ─── Python AST extractor ────────────────────────────────────────────


class _PyComplexityVisitor(ast.NodeVisitor):
    """McCabe cyclomatic complexity walker. Mirrors loc.rs::ComplexityVisitor.

    Base = 1. +1 per decision point: if, match arm (n-1), while, for, try,
    except handler, and/or (per extra operand), comprehension generator,
    if-expr (ternary), lambda."""

    def __init__(self) -> None:
        self.complexity = 1

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        # `try` itself is not a decision point — each except handler is.
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # `a and b and c` → BoolOp with 3 operands = 2 `and` decisions.
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        # Single-case match adds 0; n-case adds (n-1) per McCabe.
        self.complexity += max(0, len(node.cases) - 1)
        self.generic_visit(node)

    def _visit_comprehension(self, node: ast.AST) -> None:
        # Each `for` clause in a comprehension is an implicit loop.
        gens = getattr(node, "generators", [])
        for gen in gens:
            self.complexity += 1
            # `if` clauses inside the generator are additional decisions.
            self.complexity += len(getattr(gen, "ifs", []))
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Closures contribute a path (mirrors syn ExprClosure).
        self.complexity += 1
        self.generic_visit(node)


def _python_compute_complexity(body: list[ast.stmt]) -> int:
    """Compute McCabe complexity over the body of a function/method."""
    v = _PyComplexityVisitor()
    for stmt in body:
        v.visit(stmt)
    return v.complexity


_TEST_DECORATOR_NAMES = {
    "test", "fixture", "pytest.fixture", "pytest.mark.asyncio",
}


def _decorator_names(deco_list: list[ast.expr]) -> list[str]:
    """Render decorator AST nodes into 'name' / 'mod.name' strings."""
    names = []
    for d in deco_list:
        if isinstance(d, ast.Name):
            names.append(d.id)
        elif isinstance(d, ast.Attribute):
            parts = []
            cur: ast.AST | None = d
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            names.append(".".join(reversed(parts)))
        elif isinstance(d, ast.Call):
            # @decorator(args) — render the call target.
            tgt = d.func
            if isinstance(tgt, ast.Name):
                names.append(tgt.id)
            elif isinstance(tgt, ast.Attribute):
                names.extend(_decorator_names([tgt]))
    return names


def _is_test_function(name: str, decos: list[str], path: str) -> bool:
    if name.startswith("test_") or name == "test":
        return True
    if any(d in _TEST_DECORATOR_NAMES for d in decos):
        return True
    if any(d.endswith(".test") or d.endswith(".fixture") for d in decos):
        return True
    # File-level conventions: tests/ subdir, conftest, *_test.py / test_*.py
    norm = path.replace("\\", "/")
    if "/tests/" in norm or norm.startswith("tests/"):
        return True
    base = norm.rsplit("/", 1)[-1]
    return (
        base.startswith("test_")
        or base.endswith(("_test.py", "_tests.py"))
        or base == "conftest.py"
    )


def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render `def name(args) -> ret:`. Uses ast.unparse (3.9+)."""
    try:
        args = ast.unparse(node.args)
    except AttributeError:
        # Fallback for ancient pythons (kaizen requires 3.10+, so unlikely).
        args = ", ".join(a.arg for a in node.args.args)
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    ret = ""
    if node.returns is not None:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except AttributeError:
            ret = " -> ..."
    return f"{prefix}{node.name}({args}){ret}"


def extract_python_functions(source: str, file: str) -> list[FunctionInfo]:
    """Public entry point — parse a Python file's source into per-symbol
    records. Returns `[]` on SyntaxError so exotic syntax doesn't break
    the whole indexer run."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    source_bytes = source.encode("utf-8")
    out: list[FunctionInfo] = []
    scope: list[str] = []

    def qualified(name: str) -> str:
        return ".".join(scope + [name]) if scope else name

    def record_function(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_kind: str | None,
    ) -> None:
        name = node.name
        is_async = isinstance(node, ast.AsyncFunctionDef)
        decos = _decorator_names(node.decorator_list)

        if parent_kind == "class":
            # Distinguish method / classmethod / staticmethod / async-method.
            if "staticmethod" in decos:
                kind = "static-method"
            elif "classmethod" in decos:
                kind = "class-method"
            elif "abstractmethod" in decos:
                kind = "abstract-method"
            elif is_async:
                kind = "async-method"
            else:
                kind = "method"
        else:
            kind = "async-function" if is_async else "function"

        line_start = node.lineno
        line_end = getattr(node, "end_lineno", line_start) or line_start
        col_start = node.col_offset
        col_end = getattr(node, "end_col_offset", None)
        physical = max(1, line_end - line_start + 1)
        complexity = _python_compute_complexity(node.body)

        # Byte range via ast.get_source_segment is the safest cross-version path.
        # When unavailable (very rare), fall back to line-based slicing.
        segment = ast.get_source_segment(source, node, padded=False) or ""
        # Build byte_start/end by counting bytes up to start position.
        lines = source.encode("utf-8").split(b"\n")
        byte_start = sum(len(lines[i]) + 1 for i in range(line_start - 1))
        seg_bytes = segment.encode("utf-8")
        byte_end = byte_start + len(seg_bytes)
        body_sha = hashlib.sha1(seg_bytes).hexdigest()[:16]

        # Logical lines = non-blank, non-comment lines inside the body.
        logical = 0
        for raw in segment.split("\n"):
            t = raw.strip()
            if t and not t.startswith("#"):
                logical += 1

        # Docstring detection — ast.get_docstring is the canonical check.
        has_docstring = bool(ast.get_docstring(node))

        is_public = not name.startswith("_") or name.startswith("__") and name.endswith("__")
        is_test = _is_test_function(name, decos, file)
        signature = _render_signature(node)
        sig_hash = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]

        out.append(FunctionInfo(
            path=file,
            language="Python",
            symbol_kind=kind,
            symbol_name=name,
            qualified_name=qualified(name),
            parent_symbol=scope[-1] if scope else None,
            line_start=line_start,
            line_end=line_end,
            col_start=col_start,
            col_end=col_end,
            byte_start=byte_start,
            byte_end=byte_end,
            physical_lines=physical,
            logical_lines=logical,
            cyclomatic=complexity,
            cognitive=None,
            nesting_depth=len(scope),
            has_docstring=has_docstring,
            is_test=is_test,
            is_async=is_async,
            is_public=is_public,
            signature=signature,
            signature_hash=sig_hash,
            body_sha=body_sha,
            parser="ast",
        ))

    def record_class(node: ast.ClassDef) -> None:
        line_start = node.lineno
        line_end = getattr(node, "end_lineno", line_start) or line_start
        segment = ast.get_source_segment(source, node, padded=False) or ""
        lines = source.encode("utf-8").split(b"\n")
        byte_start = sum(len(lines[i]) + 1 for i in range(line_start - 1))
        seg_bytes = segment.encode("utf-8")
        out.append(FunctionInfo(
            path=file,
            language="Python",
            symbol_kind="class",
            symbol_name=node.name,
            qualified_name=qualified(node.name),
            parent_symbol=scope[-1] if scope else None,
            line_start=line_start,
            line_end=line_end,
            col_start=node.col_offset,
            col_end=getattr(node, "end_col_offset", None),
            byte_start=byte_start,
            byte_end=byte_start + len(seg_bytes),
            physical_lines=max(1, line_end - line_start + 1),
            logical_lines=None,
            cyclomatic=None,
            nesting_depth=len(scope),
            has_docstring=bool(ast.get_docstring(node)),
            is_test=False,
            is_async=False,
            is_public=not node.name.startswith("_"),
            signature=f"class {node.name}",
            signature_hash=hashlib.sha1(node.name.encode()).hexdigest()[:16],
            body_sha=hashlib.sha1(seg_bytes).hexdigest()[:16],
            parser="ast",
        ))

    def walk(node: ast.AST, parent_kind: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                record_function(child, parent_kind)
                # Recurse into the function body for nested defs/classes.
                scope.append(child.name)
                walk(child, "function")
                scope.pop()
            elif isinstance(child, ast.ClassDef):
                record_class(child)
                scope.append(child.name)
                walk(child, "class")
                scope.pop()
            else:
                walk(child, parent_kind)

    walk(tree, None)
    return out


# ─── Regex fallback (non-Python languages) ───────────────────────────


_REGEX_PATTERNS: dict[str, list[tuple[str, re.Pattern]]] = {
    "Rust": [
        ("function", re.compile(
            r"^\s*(?:pub(?:\(.+?\))?\s+)?(?:async\s+)?fn\s+(\w+)",
            re.MULTILINE,
        )),
    ],
    "TypeScript": [
        ("function", re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[<(]",
            re.MULTILINE,
        )),
        ("method", re.compile(
            r"^\s*(?:public|private|protected|static|async)?\s*(\w+)\s*\([^)]*\)\s*[:{]",
            re.MULTILINE,
        )),
    ],
    "JavaScript": [
        ("function", re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
            re.MULTILINE,
        )),
    ],
    "Go": [
        ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s+)?(\w+)\s*\(", re.MULTILINE)),
    ],
    "Java": [
        ("method", re.compile(
            r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*"
            r"[\w<>,\[\]]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{",
            re.MULTILINE,
        )),
    ],
    "Shell": [
        ("function", re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\s*\)\s*\{", re.MULTILINE)),
    ],
}


def extract_regex_functions(source: str, file: str, language: str) -> list[FunctionInfo]:
    """Best-effort regex extraction for non-Python languages. Marks parser='regex'.

    Carries less detail than AST extraction — no complexity, no logical
    lines, no docstring. Useful for coarse-grained search until tree-sitter
    lands (Phase 4)."""
    patterns = _REGEX_PATTERNS.get(language)
    if not patterns:
        return []
    out: list[FunctionInfo] = []
    source_bytes = source.encode("utf-8")
    seen_lines: set[int] = set()
    for kind, pattern in patterns:
        for m in pattern.finditer(source):
            line_start = source[:m.start()].count("\n") + 1
            if line_start in seen_lines:
                continue
            seen_lines.add(line_start)
            name = m.group(1)
            # Heuristic end-line: next blank line OR next pattern match.
            tail = source[m.start():]
            # Find a closing brace at column 0 (rough), else +20 lines.
            close_match = re.search(r"\n\}\s*\n", tail) if language != "Python" else None
            if close_match:
                line_end = line_start + tail[:close_match.end()].count("\n")
            else:
                line_end = line_start + 1
            byte_start = len(source[:m.start()].encode("utf-8"))
            byte_end = byte_start + len(tail[:min(len(tail), 2000)].encode("utf-8"))
            out.append(FunctionInfo(
                path=file,
                language=language,
                symbol_kind=kind,
                symbol_name=name,
                qualified_name=name,
                line_start=line_start,
                line_end=line_end,
                physical_lines=max(1, line_end - line_start + 1),
                byte_start=byte_start,
                byte_end=byte_end,
                body_sha=hashlib.sha1(name.encode()).hexdigest()[:16],
                signature=m.group(0).strip()[:120],
                parser="regex",
            ))
    return out


# ─── File-level metrics + walker ─────────────────────────────────────


@dataclass
class FileMetrics:
    path: str
    language: str
    physical_lines: int = 0
    logical_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    symbols: list[FunctionInfo] = field(default_factory=list)
    sha: str = ""

    @property
    def comment_density(self) -> float:
        if self.physical_lines == 0:
            return 0.0
        return self.comment_lines / self.physical_lines

    @property
    def god_tier(self) -> str | None:
        if self.language == "Markdown":
            return None
        if self.physical_lines > GOD_CRITICAL_LINES:
            return "critical"
        if self.physical_lines > GOD_WARNING_LINES:
            return "warning"
        return None

    @property
    def max_function_lines(self) -> int:
        if not self.symbols:
            return 0
        return max(s.physical_lines for s in self.symbols)

    @property
    def test_symbol_count(self) -> int:
        return sum(1 for s in self.symbols if s.is_test)


_COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    "Python": ("#",),
    "Shell": ("#",),
    "YAML": ("#",),
    "TOML": ("#",),
    "Ruby": ("#",),
    "GraphQL": ("#",),
    "Rust": ("//",),
    "TypeScript": ("//",),
    "JavaScript": ("//",),
    "Go": ("//",),
    "Java": ("//",),
    "Kotlin": ("//",),
    "Scala": ("//",),
    "Swift": ("//",),
    "C#": ("//",),
    "C": ("//",),
    "C++": ("//",),
    "CSS": ("/*",),
    "SQL": ("--",),
    "HTML": ("<!--",),
}


def analyze_file(path: Path, root: Path) -> FileMetrics | None:
    """Read a file, classify lines, extract symbols. Returns None for
    binary / unreadable / unknown-ext files."""
    ext = path.suffix.lstrip(".").lower()
    language = LANG_BY_EXT.get(ext)
    if not language:
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None
    # Binary sniff: null bytes in the first 1024 bytes.
    if b"\x00" in data[:1024]:
        return None
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
    metrics = FileMetrics(
        path=rel,
        language=language,
        sha=hashlib.sha1(data).hexdigest()[:16],
    )

    prefixes = _COMMENT_PREFIXES.get(language, ())
    for line in content.split("\n"):
        metrics.physical_lines += 1
        t = line.strip()
        if not t:
            metrics.blank_lines += 1
            continue
        if prefixes and any(t.startswith(p) for p in prefixes):
            metrics.comment_lines += 1
            continue
        metrics.logical_lines += 1

    # Drop trailing pseudo-line introduced by `.split("\n")` for files
    # ending with a newline. Real files: physical_lines = number of newlines + 1
    # if no trailing newline, otherwise = number of newlines.
    if content.endswith("\n"):
        metrics.physical_lines -= 1
        if metrics.blank_lines > 0:
            metrics.blank_lines -= 1

    # Symbol extraction
    if language == "Python":
        metrics.symbols = extract_python_functions(content, rel)
    else:
        metrics.symbols = extract_regex_functions(content, rel, language)

    return metrics


def iter_source_files(root: Path) -> list[Path]:
    """Walk `root` for source files, skipping ignore dirs + binary suffixes.
    Sort for stable indexing order. Ignore-dir patterns are matched against
    paths *relative to root* — so indexing a repo that itself lives inside
    `.claude/` doesn't reject every file."""
    root_resolved = root.resolve()
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = "/" + str(Path(dirpath).resolve().relative_to(root_resolved)) + "/"
        rel = rel.replace("//", "/")
        if any(seg in rel for seg in IGNORE_DIRS):
            dirnames[:] = []
            continue
        for name in filenames:
            if name.endswith(IGNORE_SUFFIXES):
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in LANG_BY_EXT:
                continue
            out.append(Path(dirpath) / name)
    out.sort()
    return out


# ─── SQLite ──────────────────────────────────────────────────────────


_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS loc_symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        language TEXT NOT NULL,
        symbol_kind TEXT NOT NULL,
        symbol_name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        parent_symbol TEXT,
        line_start INTEGER NOT NULL,
        line_end INTEGER NOT NULL,
        col_start INTEGER,
        col_end INTEGER,
        byte_start INTEGER NOT NULL,
        byte_end INTEGER NOT NULL,
        physical_lines INTEGER NOT NULL,
        logical_lines INTEGER,
        cyclomatic INTEGER,
        cognitive INTEGER,
        nesting_depth INTEGER,
        has_docstring INTEGER NOT NULL,
        is_test INTEGER NOT NULL,
        is_async INTEGER NOT NULL,
        is_public INTEGER NOT NULL,
        signature TEXT,
        signature_hash TEXT,
        body_sha TEXT NOT NULL,
        parser TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(path, line_start, symbol_name)
    );
    CREATE INDEX IF NOT EXISTS idx_loc_path     ON loc_symbols(path);
    CREATE INDEX IF NOT EXISTS idx_loc_lang     ON loc_symbols(language);
    CREATE INDEX IF NOT EXISTS idx_loc_kind     ON loc_symbols(symbol_kind);
    CREATE INDEX IF NOT EXISTS idx_loc_lines    ON loc_symbols(physical_lines DESC);
    CREATE INDEX IF NOT EXISTS idx_loc_complex  ON loc_symbols(cyclomatic DESC);
    CREATE INDEX IF NOT EXISTS idx_loc_name     ON loc_symbols(symbol_name);
    CREATE INDEX IF NOT EXISTS idx_loc_qname    ON loc_symbols(qualified_name);
    CREATE INDEX IF NOT EXISTS idx_loc_range    ON loc_symbols(path, line_start, line_end);

    CREATE TABLE IF NOT EXISTS loc_files (
        path TEXT PRIMARY KEY,
        language TEXT NOT NULL,
        physical_lines INTEGER NOT NULL,
        logical_lines INTEGER NOT NULL,
        comment_lines INTEGER NOT NULL,
        blank_lines INTEGER NOT NULL,
        symbol_count INTEGER NOT NULL,
        test_symbol_count INTEGER NOT NULL,
        god_tier TEXT,
        max_function_lines INTEGER NOT NULL,
        comment_density REAL NOT NULL,
        sha TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_loc_files_lang ON loc_files(language);
    CREATE INDEX IF NOT EXISTS idx_loc_files_god  ON loc_files(god_tier);

    CREATE TABLE IF NOT EXISTS loc_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
"""


def db_path(root: Path) -> Path:
    """Project-scoped DB at `<root>/.kaizen/loc.db`, overridable via env."""
    env = os.environ.get("KAIZEN_LOC_DB")
    if env:
        return Path(env).expanduser().resolve()
    return root / ".kaizen" / "loc.db"


def open_db(root: Path, *, create: bool = True) -> sqlite3.Connection:
    return _kz_sqlite.open_indexer_db(db_path(root), _SCHEMA_SQL, create=create)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    _kz_sqlite.set_meta(conn, "loc_meta", key, value)


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    return _kz_sqlite.get_meta(conn, "loc_meta", key, default)


# ─── Data-returning helpers (also used by loc_mcp.py) ────────────────


def index_one_file(conn: sqlite3.Connection, root: Path, fp: Path) -> int | None:
    """Index a single file into an already-open connection. sha-deduped.
    Returns the number of symbols (re)written, or None if the file was
    skipped unchanged. Caller commits."""
    metrics = analyze_file(fp, root)
    if metrics is None:
        return None
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    prior = conn.execute(
        "SELECT sha FROM loc_files WHERE path = ?", (metrics.path,)
    ).fetchone()
    if prior and prior["sha"] == metrics.sha:
        return None
    conn.execute("DELETE FROM loc_symbols WHERE path = ?", (metrics.path,))
    for sym in metrics.symbols:
        conn.execute(
            """INSERT OR REPLACE INTO loc_symbols
                (path, language, symbol_kind, symbol_name, qualified_name,
                 parent_symbol, line_start, line_end, col_start, col_end,
                 byte_start, byte_end, physical_lines, logical_lines,
                 cyclomatic, cognitive, nesting_depth, has_docstring,
                 is_test, is_async, is_public, signature, signature_hash,
                 body_sha, parser, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sym.path, sym.language, sym.symbol_kind, sym.symbol_name,
             sym.qualified_name, sym.parent_symbol, sym.line_start,
             sym.line_end, sym.col_start, sym.col_end, sym.byte_start,
             sym.byte_end, sym.physical_lines, sym.logical_lines,
             sym.cyclomatic, sym.cognitive, sym.nesting_depth,
             int(sym.has_docstring), int(sym.is_test), int(sym.is_async),
             int(sym.is_public), sym.signature, sym.signature_hash,
             sym.body_sha, sym.parser, now),
        )
    conn.execute(
        """INSERT OR REPLACE INTO loc_files
            (path, language, physical_lines, logical_lines, comment_lines,
             blank_lines, symbol_count, test_symbol_count, god_tier,
             max_function_lines, comment_density, sha, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (metrics.path, metrics.language, metrics.physical_lines,
         metrics.logical_lines, metrics.comment_lines, metrics.blank_lines,
         len(metrics.symbols), metrics.test_symbol_count, metrics.god_tier,
         metrics.max_function_lines, metrics.comment_density,
         metrics.sha, now),
    )
    return len(metrics.symbols)


def delete_file(conn: sqlite3.Connection, rel_path: str) -> None:
    """Remove all rows for a file no longer present. Caller commits."""
    conn.execute("DELETE FROM loc_symbols WHERE path = ?", (rel_path,))
    conn.execute("DELETE FROM loc_files WHERE path = ?", (rel_path,))


def do_index(root: Path) -> dict:
    """Run an incremental index pass. Returns counts dict."""
    conn = open_db(root, create=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    files = iter_source_files(root)
    seen_paths: set[str] = set()
    new_files = 0
    skipped_files = 0
    new_symbols = 0
    errors = 0
    for fp in files:
        try:
            metrics = analyze_file(fp, root)
        except (OSError, ValueError) as exc:
            errors += 1
            sys.stderr.write(f"kaizen-loc: error on {fp}: {exc}\n")
            continue
        if metrics is None:
            continue
        seen_paths.add(metrics.path)
        written = index_one_file(conn, root, fp)
        if written is None:
            skipped_files += 1
        else:
            new_files += 1
            new_symbols += written
    # Remove stale rows for files no longer present.
    existing = conn.execute("SELECT path FROM loc_files").fetchall()
    stale = [r["path"] for r in existing if r["path"] not in seen_paths]
    if stale:
        conn.executemany("DELETE FROM loc_files WHERE path = ?", [(p,) for p in stale])
        conn.executemany("DELETE FROM loc_symbols WHERE path = ?", [(p,) for p in stale])
    set_meta(conn, "last_indexed_ts", now)
    set_meta(conn, "root", str(root))
    total_files = conn.execute("SELECT COUNT(*) FROM loc_files").fetchone()[0]
    total_symbols = conn.execute("SELECT COUNT(*) FROM loc_symbols").fetchone()[0]
    set_meta(conn, "total_files", str(total_files))
    set_meta(conn, "total_symbols", str(total_symbols))
    conn.commit()
    conn.close()
    return {
        "new_files": new_files,
        "skipped_files": skipped_files,
        "new_symbols": new_symbols,
        "stale_removed": len(stale),
        "errors": errors,
        "total_files": total_files,
        "total_symbols": total_symbols,
        "db": str(db_path(root)),
    }


_COMP_RE = re.compile(r"^(>=|<=|>|<|==|=)?\s*(-?\d+)$")


def _parse_compare(expr: str) -> tuple[str, int] | None:
    """Parse '>=15' or '<100' into (op, value)."""
    m = _COMP_RE.match(expr.strip())
    if not m:
        return None
    op = m.group(1) or "=="
    if op == "=":
        op = "=="
    return op, int(m.group(2))


def _row_to_symbol(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


def do_search(
    root: Path,
    *,
    name: str | None = None,
    qualified: str | None = None,
    kind: str | None = None,
    language: str | None = None,
    min_lines: int | None = None,
    max_lines: int | None = None,
    complexity: str | None = None,
    no_tests: bool = False,
    only_tests: bool = False,
    god: str | None = None,
    at: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Structured symbol search. Returns list of symbol-row dicts."""
    p = db_path(root)
    if not p.is_file():
        return []

    # `--at file:line` short-circuits: find the symbol enclosing this line.
    if at:
        if ":" not in at:
            return []
        file_part, _, line_str = at.partition(":")
        try:
            line_no = int(line_str)
        except ValueError:
            return []
        conn = open_db(root, create=False)
        rows = conn.execute(
            """SELECT * FROM loc_symbols
                WHERE (path = ? OR path LIKE ?)
                  AND line_start <= ? AND line_end >= ?
                ORDER BY (line_end - line_start) ASC
                LIMIT ?""",
            (file_part, f"%{file_part}", line_no, line_no, limit),
        ).fetchall()
        conn.close()
        return [_row_to_symbol(r) for r in rows]

    conn = open_db(root, create=False)
    where = []
    params: list = []
    if name:
        # Glob (*) → SQL LIKE; bare string → substring match.
        if "*" in name or "?" in name:
            # fnmatch glob → SQL LIKE escape
            sql_like = name.replace("*", "%").replace("?", "_")
            where.append("symbol_name LIKE ?")
            params.append(sql_like)
        else:
            where.append("symbol_name LIKE ?")
            params.append(f"%{name}%")
    if qualified:
        where.append("qualified_name LIKE ?")
        params.append(f"%{qualified}%")
    if kind:
        where.append("symbol_kind = ?")
        params.append(kind)
    if language:
        where.append("language = ?")
        params.append(language)
    if min_lines is not None:
        where.append("physical_lines >= ?")
        params.append(min_lines)
    if max_lines is not None:
        where.append("physical_lines <= ?")
        params.append(max_lines)
    if complexity:
        cmp = _parse_compare(complexity)
        if cmp:
            op, val = cmp
            where.append(f"cyclomatic {op} ?")
            params.append(val)
    if no_tests:
        where.append("is_test = 0")
    if only_tests:
        where.append("is_test = 1")

    if god:
        # JOIN against loc_files for god-tier filter.
        sql = (
            "SELECT s.* FROM loc_symbols s "
            "JOIN loc_files f ON f.path = s.path "
            "WHERE f.god_tier = ?"
        )
        params.insert(0, god)
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY s.physical_lines DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    else:
        sql = "SELECT * FROM loc_symbols"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY physical_lines DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_row_to_symbol(r) for r in rows]


def do_files(
    root: Path,
    *,
    god: str | None = None,
    language: str | None = None,
    comment_density: str | None = None,
    max_fn_lines: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """File-level search."""
    p = db_path(root)
    if not p.is_file():
        return []
    conn = open_db(root, create=False)
    where, params = [], []
    if god:
        where.append("god_tier = ?")
        params.append(god)
    if language:
        where.append("language = ?")
        params.append(language)
    if comment_density:
        cmp = _parse_compare(comment_density)
        if cmp:
            op, val = cmp
            where.append(f"comment_density {op} ?")
            params.append(float(val))
    if max_fn_lines:
        cmp = _parse_compare(max_fn_lines)
        if cmp:
            op, val = cmp
            where.append(f"max_function_lines {op} ?")
            params.append(val)
    sql = "SELECT * FROM loc_files"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY physical_lines DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{k: r[k] for k in r.keys()} for r in rows]


def do_show(root: Path, symbol_id: int) -> dict | None:
    """Fetch symbol + extract source via byte range."""
    p = db_path(root)
    if not p.is_file():
        return None
    conn = open_db(root, create=False)
    r = conn.execute(
        "SELECT * FROM loc_symbols WHERE id = ?", (symbol_id,)
    ).fetchone()
    conn.close()
    if not r:
        return None
    sym = _row_to_symbol(r)
    file_path = root / sym["path"]
    if file_path.is_file():
        try:
            data = file_path.read_bytes()
            segment = data[sym["byte_start"]:sym["byte_end"]].decode(
                "utf-8", errors="replace"
            )
            sym["source"] = segment
        except OSError:
            sym["source"] = None
    return sym


def do_get(root: Path, symbol_id: int) -> dict | None:
    """Bare row fetch (no source extraction). Mirrors knowledge_index.do_get."""
    p = db_path(root)
    if not p.is_file():
        return None
    conn = open_db(root, create=False)
    r = conn.execute(
        "SELECT * FROM loc_symbols WHERE id = ?", (symbol_id,)
    ).fetchone()
    conn.close()
    return _row_to_symbol(r) if r else None


def do_stats(root: Path, by: str | None = None) -> dict:
    """Index stats. `by` can be 'language' or 'kind' for grouped counts."""
    p = db_path(root)
    if not p.is_file():
        return {"indexed": False, "db_path": str(p)}
    conn = open_db(root, create=False)
    out: dict = {
        "indexed": True,
        "db_path": str(p),
        "root": get_meta(conn, "root", str(root)),
        "last_indexed_ts": get_meta(conn, "last_indexed_ts", ""),
        "total_files": int(get_meta(conn, "total_files", "0") or 0),
        "total_symbols": int(get_meta(conn, "total_symbols", "0") or 0),
    }
    if by == "language":
        rows = conn.execute(
            "SELECT language, COUNT(*) AS n FROM loc_symbols GROUP BY language"
        ).fetchall()
        out["by_language"] = {r["language"]: r["n"] for r in rows}
    elif by == "kind":
        rows = conn.execute(
            "SELECT symbol_kind, COUNT(*) AS n FROM loc_symbols GROUP BY symbol_kind"
        ).fetchall()
        out["by_kind"] = {r["symbol_kind"]: r["n"] for r in rows}
    conn.close()
    return out


def do_report(root: Path) -> dict:
    """xtask-style verdict: god files, top largest fns, top complex fns,
    comment density, code/test ratio."""
    p = db_path(root)
    if not p.is_file():
        return {"indexed": False}
    conn = open_db(root, create=False)
    # Per-language file stats
    lang_rows = conn.execute(
        """SELECT language, COUNT(*) AS files, SUM(physical_lines) AS total,
                  SUM(logical_lines) AS logical, SUM(comment_lines) AS comments,
                  SUM(blank_lines) AS blanks
           FROM loc_files GROUP BY language ORDER BY total DESC"""
    ).fetchall()
    languages = [
        {
            "language": r["language"],
            "files": r["files"],
            "physical": r["total"],
            "logical": r["logical"],
            "comments": r["comments"],
            "blanks": r["blanks"],
        }
        for r in lang_rows
    ]
    god_rows = conn.execute(
        "SELECT path, physical_lines, god_tier FROM loc_files "
        "WHERE god_tier IS NOT NULL ORDER BY physical_lines DESC LIMIT 10"
    ).fetchall()
    top_largest = conn.execute(
        "SELECT * FROM loc_symbols WHERE symbol_kind != 'class' "
        "ORDER BY physical_lines DESC LIMIT 10"
    ).fetchall()
    top_complex = conn.execute(
        "SELECT * FROM loc_symbols WHERE cyclomatic IS NOT NULL "
        "ORDER BY cyclomatic DESC LIMIT 10"
    ).fetchall()
    totals_row = conn.execute(
        "SELECT SUM(physical_lines) AS total, SUM(comment_lines) AS comments, "
        "       COUNT(*) AS files FROM loc_files"
    ).fetchone()
    total_lines = totals_row["total"] or 0
    total_comments = totals_row["comments"] or 0
    comment_density = (total_comments / total_lines * 100) if total_lines else 0.0
    conn.close()
    return {
        "indexed": True,
        "total_files": totals_row["files"] or 0,
        "total_lines": total_lines,
        "comment_density_pct": round(comment_density, 1),
        "languages": languages,
        "god_files": [
            {"path": r["path"], "lines": r["physical_lines"], "tier": r["god_tier"]}
            for r in god_rows
        ],
        "top_largest": [_row_to_symbol(r) for r in top_largest],
        "top_complex": [_row_to_symbol(r) for r in top_complex],
    }


# ─── CLI ─────────────────────────────────────────────────────────────


def _resolve_root(args: argparse.Namespace) -> Path:
    if getattr(args, "root", None):
        return Path(args.root).expanduser().resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return Path(out) if out else Path.cwd()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


class LocCLI(IndexerCLI):
    PROG = "kaizen-loc"
    DESCRIPTION = "Function-level codebase metrics + per-symbol search."
    # Exclude the default `search` (which assumes a positional `query`);
    # loc's search is all-flags. We register our own search subparser in
    # `register_extra_subcommands` below.
    STANDARD_SUBCOMMANDS = ("index", "reindex", "stats", "get", "path", "clear")

    def db_path_for(self, args: argparse.Namespace) -> Path:
        return db_path(_resolve_root(args))

    # ─── do_* overrides ──────────────────────────────────────────────

    def do_index(self, args):
        return do_index(_resolve_root(args))

    def do_stats(self, args):
        return do_stats(_resolve_root(args), by=getattr(args, "by", None))

    def do_get(self, args):
        return do_get(_resolve_root(args), args.id)

    def do_search(self, args):
        return do_search(
            _resolve_root(args),
            name=getattr(args, "name", None),
            qualified=getattr(args, "qualified", None),
            kind=getattr(args, "kind", None),
            language=getattr(args, "language", None),
            min_lines=getattr(args, "min_lines", None),
            max_lines=getattr(args, "max_lines", None),
            complexity=getattr(args, "complexity", None),
            no_tests=getattr(args, "no_tests", False),
            only_tests=getattr(args, "only_tests", False),
            god=getattr(args, "god", None),
            at=getattr(args, "at", None),
            limit=args.top_k,
        )

    # ─── Extra subcommands (files / show / report) ──────────────────

    def register_extra_subcommands(self, sub):
        # Loc's `search` is structured (all flags, no positional query).
        psr = sub.add_parser("search", help="structured symbol search")
        psr.add_argument("--root")
        psr.add_argument("--top-k", type=int, default=50)
        psr.add_argument("--json", action="store_true")
        self.extra_search_args(psr)
        psr.set_defaults(func=self.cmd_search)

        pf = sub.add_parser("files", help="file-level search")
        pf.add_argument("--root", help="repo root (default: git toplevel)")
        pf.add_argument("--god", choices=["critical", "warning"])
        pf.add_argument("--language")
        pf.add_argument("--comment-density", help="e.g. '<0.05'")
        pf.add_argument("--max-fn-lines", help="e.g. '>200'")
        pf.add_argument("--limit", type=int, default=100)
        pf.add_argument("--json", action="store_true")
        pf.set_defaults(func=self.cmd_files)

        ps = sub.add_parser("show", help="print symbol source by id")
        ps.add_argument("id", type=int)
        ps.add_argument("--root")
        ps.add_argument("--json", action="store_true")
        ps.set_defaults(func=self.cmd_show)

        pr = sub.add_parser("report", help="xtask-style verdict")
        pr.add_argument("--root")
        pr.add_argument("--json", action="store_true")
        pr.set_defaults(func=self.cmd_report)

    def cmd_files(self, args):
        results = do_files(
            _resolve_root(args),
            god=args.god,
            language=args.language,
            comment_density=args.comment_density,
            max_fn_lines=args.max_fn_lines,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(results, indent=2, default=str))
            return
        for r in results:
            tag = f"[{r['god_tier'].upper()}] " if r["god_tier"] else ""
            print(
                f"  {tag}{r['physical_lines']:>5} lines · "
                f"{r['symbol_count']:>3} symbols · {r['path']}"
            )

    def cmd_show(self, args):
        result = do_show(_resolve_root(args), args.id)
        if not result:
            sys.exit(f"id {args.id} not found")
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return
        print(f"# {result['qualified_name']} ({result['path']}:"
              f"{result['line_start']}-{result['line_end']})")
        print(f"# kind: {result['symbol_kind']} · cyclomatic: "
              f"{result['cyclomatic']} · {result['physical_lines']} lines")
        print()
        print(result.get("source") or "(source unavailable)")

    def cmd_report(self, args):
        result = do_report(_resolve_root(args))
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return
        if not result.get("indexed"):
            print("kaizen-loc: no index yet — run `index` first")
            return
        print(f"--- Codebase Report ---")
        print(f"total files: {result['total_files']}")
        print(f"total lines: {result['total_lines']}")
        print(f"comment density: {result['comment_density_pct']}%")
        print()
        print("Per-language:")
        for L in result["languages"]:
            print(f"  {L['language']:<14} {L['files']:>5} files  "
                  f"{L['physical']:>8} physical  {L['logical']:>8} logical")
        print()
        if result["god_files"]:
            print("God files (>500 lines):")
            for g in result["god_files"]:
                print(f"  [{g['tier'].upper():<8}] {g['lines']:>5} lines  {g['path']}")
            print()
        if result["top_largest"]:
            print("Top largest functions:")
            for s in result["top_largest"]:
                cx = s.get("cyclomatic") or "?"
                print(f"  {s['physical_lines']:>5} lines · cx {cx:>3} · "
                      f"{s['path']}:{s['line_start']}-{s['line_end']}")
                print(f"        {s['qualified_name']}")
            print()
        if result["top_complex"]:
            print("Top complex functions (cyclomatic):")
            for s in result["top_complex"]:
                print(f"  cx {s['cyclomatic']:>3} · {s['physical_lines']:>5} lines · "
                      f"{s['path']}:{s['line_start']}-{s['line_end']}")
                print(f"        {s['qualified_name']}")

    # ─── Argparse hooks ──────────────────────────────────────────────

    def extra_index_args(self, p):
        p.add_argument("--root", help="repo root (default: git toplevel)")

    def extra_reindex_args(self, p):
        p.add_argument("--root")

    def extra_search_args(self, p):
        # NOTE: `--root` is added in register_extra_subcommands so the
        # custom search parser doesn't double-define it.
        p.add_argument("--name", help="substring or glob (e.g. '*carve*')")
        p.add_argument("--qualified", help="match against qualified_name")
        p.add_argument("--kind", help="function | method | class | ...")
        p.add_argument("--language", help="Python | Rust | ...")
        p.add_argument("--min-lines", type=int)
        p.add_argument("--max-lines", type=int)
        p.add_argument("--complexity", help="e.g. '>=15'")
        p.add_argument("--no-tests", action="store_true")
        p.add_argument("--only-tests", action="store_true")
        p.add_argument("--god", choices=["critical", "warning"])
        p.add_argument("--at", help="enclosing symbol for <file>:<line>")

    def extra_stats_args(self, p):
        p.add_argument("--root")
        p.add_argument("--by", choices=["language", "kind"])
        p.add_argument("--json", action="store_true")

    def extra_get_args(self, p):
        p.add_argument("--root")

    def extra_path_args(self, p):
        p.add_argument("--root")

    def extra_clear_args(self, p):
        p.add_argument("--root")

    # ─── Render overrides ────────────────────────────────────────────

    def print_index(self, result, args):
        if not result:
            return
        sys.stderr.write(
            f"kaizen-loc: indexed {result['new_files']} new, "
            f"skipped {result['skipped_files']} unchanged, "
            f"removed {result['stale_removed']} stale "
            f"({result['errors']} errors)\n"
            f"  total: {result['total_files']} files, "
            f"{result['total_symbols']} symbols at {result['db']}\n"
        )

    def print_search(self, results, args):
        if not results:
            print("(no matches)")
            return
        for r in results:
            cx = r.get("cyclomatic")
            cx_str = f"cx {cx:>3} · " if cx is not None else ""
            test_tag = " [test]" if r["is_test"] else ""
            async_tag = " [async]" if r["is_async"] else ""
            print(
                f"  {r['physical_lines']:>5} lines · {cx_str}"
                f"{r['path']}:{r['line_start']}-{r['line_end']}{test_tag}{async_tag}"
            )
            print(f"        {r['symbol_kind']} {r['qualified_name']}  (id={r['id']})")

    def print_stats(self, s, args):
        if not s.get("indexed"):
            print("kaizen-loc: no index yet — run `index` first")
            return
        print(f"db:        {s['db_path']}")
        print(f"root:      {s.get('root', '?') or '?'}")
        print(f"indexed:   {s.get('last_indexed_ts', '?') or '?'}")
        print(f"files:     {s['total_files']}")
        print(f"symbols:   {s['total_symbols']}")
        for key in ("by_language", "by_kind"):
            if key in s:
                print(f"\n{key}:")
                for k, n in sorted(s[key].items(), key=lambda kv: kv[1], reverse=True):
                    print(f"  {k:<20} {n}")


def main():
    LocCLI().run()


if __name__ == "__main__":
    main()
