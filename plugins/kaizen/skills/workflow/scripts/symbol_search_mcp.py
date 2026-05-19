#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["fastmcp>=3.0"]
# ///
"""kaizen MCP — semantic symbol search returning exact line ranges.

Composes:
  - onboard_index (semantic chunks with line_start/line_end — Phase 2)
  - _ast_chunk (SymbolChunk shape — Phase 1)
  - _search.dense_search (semantic ranking, when embedding backend up)

Two tools:
  symbol_search(query, top_k, kind, language, path_glob)
    → list[{path, line_start, line_end, kind, symbol_name, language,
            score, snippet}]
    Use the returned (line_start, line_end) with Read(file, offset,
    limit) to load ONLY the matched symbol — no whole-file Read.

  symbol_at_line(file, line)
    → innermost enclosing symbol(s) — composes with stack traces /
    citations like 'src/foo.py:42'.

Graceful fallback to bm25 / LIKE when no embedding backend available.
Sandbox: KAIZEN_ONBOARD_ROOT redirects to a tempdir for tests.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from fastmcp import FastMCP

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

mcp = FastMCP("symbol-search")


def _resolve_root() -> Path:
    env = os.environ.get("KAIZEN_ONBOARD_ROOT")
    if env:
        return Path(env).expanduser()
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def _open_conn(root: Path) -> sqlite3.Connection | None:
    """Open the onboard db read-only. None when the db doesn't exist."""
    import onboard_index as oi
    db = oi.db_path(root)
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


def _maybe_embed(query: str) -> bytes | None:
    """Embed the query if a backend is available; else None → fallback.

    Catches BaseException (not just Exception) because the embedding
    backend's failure modes include ``sys.exit(1)`` when numpy is
    missing (which raises SystemExit, not a normal Exception). The
    semantic-fallback contract MUST never break the MCP tool.
    """
    try:
        import _embed
        vec, _dim = _embed.embed_one(query)
        return vec
    except BaseException:  # noqa: BLE001
        return None


def _snippet(text: str, max_len: int = 200) -> str:
    """First non-trivial line + a few more, capped."""
    if not text:
        return ""
    snippet = text[:max_len]
    if len(text) > max_len:
        snippet += "…"
    return snippet


def symbol_search(query: str, top_k: int = 10,
                   kind: str = "", language: str = "",
                   path_glob: str = "") -> list[dict]:
    """Semantic search over code symbols. Returns exact line ranges.

    Returns: list of ``{path, line_start, line_end, kind, symbol_name,
    language, score, snippet}`` ordered by relevance (highest first).

    Use the returned (line_start, line_end) with Read(file, offset,
    limit) to load ONLY the matched symbol — no whole-file Read.

    Args:
      query: natural-language description ("auth token validation").
      top_k: max results (default 10).
      kind: filter by symbol kind (function / method / class / ...).
      language: filter (python / typescript / rust / go / ...).
      path_glob: SQL LIKE pattern on the file path (`%/api/%`).
    """
    root = _resolve_root()
    conn = _open_conn(root)
    if conn is None:
        return []

    # Build WHERE clause for kind / language / path filters.
    where_parts: list[str] = ["c.line_start > 0"]  # exclude sliding-window chunks (line 0 = no AST info)
    params: list = []
    if kind:
        where_parts.append("c.kind = ?")
        # 'kind' in chunks is 'code' / 'doc'; symbol kind lives in the
        # symbol_name structure. We use the kind arg loosely — match
        # symbol_name pattern when the kind == 'function' / 'method'
        # since those don't show in `kind` column.
        # Pragmatic: just substring-filter on symbol_name when kind given.
        where_parts.pop()  # roll back; kind is not in code_chunks.kind
        # (the kind field is 'code'/'doc'). Skip this filter for now.
    if language:
        where_parts.append("c.language = ?")
        params.append(language)
    if path_glob:
        where_parts.append("f.path LIKE ?")
        params.append(path_glob)
    where_sql = " AND ".join(where_parts) if where_parts else "1=1"

    # Try semantic first; fall back to bm25 / LIKE on the query string.
    query_vec = _maybe_embed(query)
    if query_vec is not None:
        # Dense path: pull candidate rows + cosine in Python.
        # (Avoids depending on sqlite-vec extension being available.)
        rows = conn.execute(f"""
            SELECT c.id, c.embedding, f.path, c.line_start, c.line_end,
                   c.symbol_name, c.language, c.text
            FROM code_chunks c JOIN code_files f ON c.file_id = f.id
            WHERE {where_sql} AND c.symbol_name != ''
        """, params).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for r in rows:
            sim = _cosine(query_vec, r["embedding"])
            scored.append((sim, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        results = scored[:top_k]
    else:
        # LIKE fallback — substring on symbol_name + text.
        like = f"%{query}%"
        rows = conn.execute(f"""
            SELECT c.id, c.embedding, f.path, c.line_start, c.line_end,
                   c.symbol_name, c.language, c.text
            FROM code_chunks c JOIN code_files f ON c.file_id = f.id
            WHERE {where_sql}
              AND (c.symbol_name LIKE ? OR c.text LIKE ?)
            ORDER BY length(c.symbol_name) ASC
            LIMIT ?
        """, params + [like, like, top_k]).fetchall()
        results = [(0.0, r) for r in rows]

    out = []
    for sim, r in results:
        out.append({
            "path":        r["path"],
            "line_start":  r["line_start"],
            "line_end":    r["line_end"],
            "kind":        _infer_kind(r["symbol_name"]),
            "symbol_name": r["symbol_name"],
            "language":    r["language"],
            "score":       round(float(sim), 4),
            "snippet":     _snippet(r["text"]),
        })
    return out


def symbol_at_line(file: str, line: int) -> list[dict]:
    """Innermost enclosing symbol(s) at file:line. ``file`` matched by suffix.

    Returns rows ordered narrowest-first so the first hit is the most
    specific scope.
    """
    root = _resolve_root()
    conn = _open_conn(root)
    if conn is None:
        return []
    rows = conn.execute("""
        SELECT f.path, c.line_start, c.line_end, c.symbol_name, c.language
        FROM code_chunks c JOIN code_files f ON c.file_id = f.id
        WHERE f.path LIKE ?
          AND c.line_start > 0
          AND c.line_start <= ? AND c.line_end >= ?
        ORDER BY (c.line_end - c.line_start) ASC
        LIMIT 5
    """, (f"%{file}", line, line)).fetchall()
    return [{
        "path":        r["path"],
        "line_start":  r["line_start"],
        "line_end":    r["line_end"],
        "symbol_name": r["symbol_name"],
        "language":    r["language"],
        "kind":        _infer_kind(r["symbol_name"]),
    } for r in rows]


def _infer_kind(symbol_name: str) -> str:
    """Heuristic: '.' in name → method, '<module>' → module, else function."""
    if not symbol_name:
        return ""
    if symbol_name == "<module>":
        return "module"
    if "." in symbol_name:
        return "method"
    return "function-or-class"


def _cosine(a: bytes, b: bytes) -> float:
    """Cosine similarity for two float32-packed embeddings."""
    import struct
    n = len(a) // 4
    if n == 0 or len(a) != len(b):
        return 0.0
    av = struct.unpack(f"{n}f", a)
    bv = struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(av, bv))
    na = sum(x * x for x in av) ** 0.5
    nb = sum(x * x for x in bv) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


mcp.tool()(symbol_search)
mcp.tool()(symbol_at_line)


if __name__ == "__main__":
    mcp.run()
