"""AST-aware symbol chunking for Python — roadmap O2 (minimal).

The existing `_chunk.chunk_text` uses sentence-boundary heuristics. For
Python source that's suboptimal: function bodies get split across
chunks, losing the cohesive "this is one function" signal that helps
both retrieval and reading.

This module provides Python-specific symbol-aware chunking. It uses
stdlib `ast` (same parser that runs the X1 loc indexer's
`extract_python_functions`) to find function/class boundaries, then
emits ONE CHUNK per top-level / class-level symbol. A symbol that
exceeds a soft byte budget is split into multiple chunks; the
boundaries are still ast-aligned (statement-level).

## Output shape

Each chunk dict carries:
  text:        the source slice (raw, not comment-stripped)
  char_start:  byte offset into the original source
  char_end:    one-past-the-end offset
  chunk_idx:   0..N-1 within the file
  symbol_name: dotted name of the enclosing symbol (e.g. 'Foo.bar')
  kind:        'function' | 'method' | 'class' | 'module' | 'block'

The first chunk of every file is a 'module' chunk capturing the
imports + module-level statements before the first function/class.

## When the source isn't parseable

Returns an empty list. Callers (the indexer) should fall back to
the generic sentence-boundary chunker.
"""
from __future__ import annotations

import ast
import dataclasses


@dataclasses.dataclass
class SymbolChunk:
    text: str
    char_start: int
    char_end: int
    chunk_idx: int
    symbol_name: str
    kind: str
    line_start: int = 0   # 1-indexed, inclusive. 0 = unknown (pre-Phase-1 callers).
    line_end: int = 0     # 1-indexed, inclusive. 0 = unknown.


def chunk_python_by_symbol(source: str, max_chars: int = 2000) -> list[SymbolChunk]:
    """Symbol-aware chunking. Returns [] when the source doesn't parse.

    Each top-level function / class is its own chunk. Nested functions
    inside a function get bundled with their parent (cohesion > granularity
    for embeddings). Classes whose body exceeds max_chars are split: one
    chunk for the class header + body up to the first method, then one
    chunk per method.

    The module-level prologue (everything before the first function/class)
    is the FIRST chunk, kind='module'. Empty prologues produce no chunk."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    src_bytes = source.encode("utf-8")
    line_starts = _line_starts(src_bytes)

    chunks: list[SymbolChunk] = []
    chunk_idx = 0

    # Walk top-level body
    body = tree.body
    if not body:
        return []

    # 1. Module prologue — everything before the first def/class.
    first_def_idx = next(
        (i for i, n in enumerate(body)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))),
        len(body),
    )
    if first_def_idx > 0:
        first = body[0]
        last = body[first_def_idx - 1]
        prologue_start = _byte_offset(src_bytes, line_starts, first.lineno, first.col_offset)
        prologue_end = _node_end_byte(src_bytes, line_starts, last)
        prologue_text = src_bytes[prologue_start:prologue_end].decode("utf-8", errors="replace")
        if prologue_text.strip():
            chunks.append(SymbolChunk(
                text=prologue_text,
                char_start=prologue_start, char_end=prologue_end,
                chunk_idx=chunk_idx, symbol_name="<module>", kind="module",
                line_start=first.lineno,
                line_end=getattr(last, "end_lineno", last.lineno) or last.lineno,
            ))
            chunk_idx += 1

    # 2. One chunk per top-level def / class. Classes that are too large
    # get sub-chunked by method.
    for node in body[first_def_idx:]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.extend(_chunk_function(node, src_bytes, line_starts, chunk_idx, parent=""))
            chunk_idx += 1
        elif isinstance(node, ast.ClassDef):
            class_chunks = _chunk_class(node, src_bytes, line_starts, chunk_idx, max_chars)
            chunks.extend(class_chunks)
            chunk_idx += len(class_chunks)
        else:
            # Top-level statement that ISN'T a def/class — accumulate into
            # the prologue? It's safer to just include it as a 'block' chunk.
            start = _byte_offset(src_bytes, line_starts, node.lineno, node.col_offset)
            end = _node_end_byte(src_bytes, line_starts, node)
            text = src_bytes[start:end].decode("utf-8", errors="replace")
            if text.strip():
                chunks.append(SymbolChunk(
                    text=text, char_start=start, char_end=end,
                    chunk_idx=chunk_idx, symbol_name="<module>", kind="block",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                ))
                chunk_idx += 1
    return chunks


def _chunk_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    src_bytes: bytes,
    line_starts: list[int],
    chunk_idx: int,
    parent: str,
) -> list[SymbolChunk]:
    """Return a single chunk for a function. Methods receive parent='Class'."""
    start = _byte_offset(src_bytes, line_starts, node.lineno, node.col_offset)
    end = _node_end_byte(src_bytes, line_starts, node)
    text = src_bytes[start:end].decode("utf-8", errors="replace")
    is_async = isinstance(node, ast.AsyncFunctionDef)
    qualified = f"{parent}.{node.name}" if parent else node.name
    return [SymbolChunk(
        text=text, char_start=start, char_end=end,
        chunk_idx=chunk_idx, symbol_name=qualified,
        kind=("async-method" if (is_async and parent) else
              "method" if parent else
              "async-function" if is_async else
              "function"),
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
    )]


def _chunk_class(
    node: ast.ClassDef,
    src_bytes: bytes,
    line_starts: list[int],
    chunk_idx: int,
    max_chars: int,
) -> list[SymbolChunk]:
    """Class chunking: small classes are ONE chunk; large classes split
    into header + per-method chunks."""
    cstart = _byte_offset(src_bytes, line_starts, node.lineno, node.col_offset)
    cend = _node_end_byte(src_bytes, line_starts, node)
    full_text = src_bytes[cstart:cend].decode("utf-8", errors="replace")
    if len(full_text) <= max_chars:
        return [SymbolChunk(
            text=full_text, char_start=cstart, char_end=cend,
            chunk_idx=chunk_idx, symbol_name=node.name, kind="class",
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
        )]
    # Large class — emit header chunk + one per method
    out: list[SymbolChunk] = []
    # Find first method-like node in body
    first_method_idx = next(
        (i for i, n in enumerate(node.body)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        len(node.body),
    )
    # Header: class line through start of first method (or end if none)
    if first_method_idx < len(node.body):
        first_method = node.body[first_method_idx]
        header_end = _byte_offset(
            src_bytes, line_starts, first_method.lineno, first_method.col_offset,
        )
    else:
        header_end = cend
    header_text = src_bytes[cstart:header_end].decode("utf-8", errors="replace")
    if header_text.strip():
        # Header line range: class line through the line before the first method.
        if first_method_idx < len(node.body):
            first_method = node.body[first_method_idx]
            header_line_end = max(node.lineno, first_method.lineno - 1)
        else:
            header_line_end = getattr(node, "end_lineno", node.lineno) or node.lineno
        out.append(SymbolChunk(
            text=header_text, char_start=cstart, char_end=header_end,
            chunk_idx=chunk_idx, symbol_name=node.name, kind="class",
            line_start=node.lineno,
            line_end=header_line_end,
        ))
    # Each method
    for i, child in enumerate(node.body[first_method_idx:]):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        method_chunks = _chunk_function(
            child, src_bytes, line_starts,
            chunk_idx + len(out), parent=node.name,
        )
        out.extend(method_chunks)
    return out


# ─── Imports extraction (for O6 xref) ─────────────────────────────────


@dataclasses.dataclass
class ImportRef:
    """A symbol an import brings into scope."""
    symbol: str        # the importable name as visible in the source
    module: str        # the source module (`from X import Y` → X; `import X` → X)
    kind: str = "import"


def extract_python_imports(source: str) -> list[ImportRef]:
    """Pull every imported symbol. Returns [] on parse failure."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bind_as = alias.asname or alias.name
                out.append(ImportRef(symbol=bind_as, module=alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                bind_as = alias.asname or alias.name
                out.append(ImportRef(symbol=bind_as, module=mod))
    return out


# ─── Source-position helpers ─────────────────────────────────────────


def _line_starts(src_bytes: bytes) -> list[int]:
    """Byte offset of the first byte of each line. line_starts[N-1] =
    offset of line N (1-indexed)."""
    out = [0]
    for i, b in enumerate(src_bytes):
        if b == 0x0A:  # newline
            out.append(i + 1)
    return out


def _byte_offset(src_bytes: bytes, line_starts: list[int], lineno: int, col: int) -> int:
    if lineno < 1 or lineno > len(line_starts):
        return 0
    # Note: `col_offset` in ast is byte-offset on bytes, char-offset on
    # str. We're computing on bytes, so direct add works correctly for
    # ASCII. For non-ASCII we'd need full UTF-8 decode walk; this is a
    # known limitation we live with (loc indexer has the same one).
    return line_starts[lineno - 1] + col


def _node_end_byte(src_bytes: bytes, line_starts: list[int], node: ast.AST) -> int:
    end_line = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if end_line is None or end_col is None:
        return len(src_bytes)
    return _byte_offset(src_bytes, line_starts, end_line, end_col)
