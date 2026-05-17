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
"""kaizen claude_docs_index — semantic search over a local Claude docs mirror.

Pairs with ericbuess/claude-code-docs (the upstream markdown mirror) and adds
the SQLite + sentence-transformers search surface the upstream lacks.

## Data flow

    upstream repo (ericbuess/claude-code-docs)
        └── markdown files (.md per topic)
            │
            │  `claude_docs_index bootstrap`  (one-time git clone)
            ▼
    KAIZEN_CLAUDE_DOCS_SRC  =  ~/.claude/.kaizen/claude-docs/src/
            │
            │  `claude_docs_index index`     (chunked sha-deduped reindex)
            ▼
    KAIZEN_CLAUDE_DOCS_DB   =  ~/.claude/.kaizen/claude-docs/index.db
            │                  ┌───────────────────────────────────────┐
            │                  │  claude_doc_chunks (per chunk + emb)  │
            │                  │  claude_doc_files  (per file shapshot)│
            │                  │  claude_doc_meta   (model, last_ts)   │
            │                  └───────────────────────────────────────┘
            │
            │  `claude_docs_index search "<query>"`  (cosine top-k)
            ▼
    ranked chunks → path/section/snippet emitted to stdout

## Subcommands

    bootstrap                            git clone the upstream docs repo
    update                               git pull the upstream
    index                                incremental (sha-deduped) reindex
    reindex                              drop tables + rebuild from scratch
    search "<query>" [--top-k N]         cosine search; ranked chunks
    stats                                file/chunk count, embed model, last ts
    get <id>                             dump one chunk's full text
    path                                 print the DB path
    clear                                rm the DB (idempotent)

## Env overrides

    KAIZEN_CLAUDE_DOCS_DIR    directory root          (default ~/.claude/.kaizen/claude-docs)
    KAIZEN_CLAUDE_DOCS_SRC    upstream checkout       (default $DIR/src)
    KAIZEN_CLAUDE_DOCS_DB     sqlite path             (default $DIR/index.db)
    KAIZEN_EMBED_BACKEND      see _embed.py for the full embed-backend surface
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _paths as _p  # noqa: E402
import _embed as _kz_embed  # noqa: E402
import _chunk as _kz_chunk  # noqa: E402
import config as _cfg  # noqa: E402
from _progress import Progress as _Progress  # noqa: E402

DB_PATH = _p.CLAUDE_DOCS_DB
SRC_DIR = _p.CLAUDE_DOCS_SRC
REPO_URL = _cfg.CLAUDE_DOCS_REPO_URL

DEFAULT_MODEL = _cfg.EMBED_MODEL
DEFAULT_DIM = _cfg.EMBED_DIM


# ─── DB (M1 — shared base in _sqlite.py) ─────────────────────────────


import _sqlite as _kz_sqlite  # noqa: E402

_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS claude_doc_files (
        path TEXT PRIMARY KEY,
        sha TEXT NOT NULL,
        chunk_count INTEGER,
        title TEXT,
        bytes INTEGER,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS claude_doc_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        chunk_idx INTEGER NOT NULL,
        char_start INTEGER,
        char_end INTEGER,
        section TEXT,
        text TEXT NOT NULL,
        embedding BLOB NOT NULL,
        FOREIGN KEY (path) REFERENCES claude_doc_files(path) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_path ON claude_doc_chunks(path);
    CREATE TABLE IF NOT EXISTS claude_doc_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
"""


def open_db(create: bool = True) -> sqlite3.Connection:
    return _kz_sqlite.open_indexer_db(DB_PATH, _SCHEMA_SQL, create=create)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    _kz_sqlite.set_meta(conn, "claude_doc_meta", key, value)


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    return _kz_sqlite.get_meta(conn, "claude_doc_meta", key, default)


# ─── Source scanning ────────────────────────────────────────────────


MD_EXTS = {".md", ".mdx"}
SKIP_DIRS = {".git", "node_modules", ".github", "scripts", "dist", "build"}


def iter_md_files(src: Path):
    """Yield every .md/.mdx file under src (excluding SKIP_DIRS)."""
    if not src.exists():
        return
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if Path(fn).suffix.lower() in MD_EXTS:
                yield Path(dirpath) / fn


def first_h1(text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def nearest_section(text: str, char_offset: int) -> str:
    """Return the most recent H1/H2/H3 header preceding char_offset."""
    prefix = text[:char_offset]
    # Walk backwards looking for the latest `^#+ ` line.
    last_header = ""
    for m in re.finditer(r"^(#{1,3})\s+(.+)$", prefix, re.MULTILINE):
        last_header = m.group(2).strip()
    return last_header


def file_sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ─── Bootstrap / update (git ops) ───────────────────────────────────


def cmd_bootstrap(args) -> dict:
    """git clone the upstream docs repo into SRC_DIR (if missing)."""
    if SRC_DIR.exists() and any(SRC_DIR.iterdir()):
        msg = f"already bootstrapped at {SRC_DIR}"
        print(msg)
        return {"status": "exists", "src": str(SRC_DIR)}
    SRC_DIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {REPO_URL} → {SRC_DIR}")
    rc = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(SRC_DIR)],
        check=False,
    ).returncode
    if rc != 0:
        sys.stderr.write(f"git clone failed (exit={rc})\n")
        sys.exit(1)
    print(f"  ✓ cloned to {SRC_DIR}")
    return {"status": "cloned", "src": str(SRC_DIR)}


def cmd_update(args) -> dict:
    """git pull the upstream docs repo (call before reindex)."""
    if not (SRC_DIR / ".git").exists():
        sys.stderr.write(
            f"{SRC_DIR} is not a git checkout — run `bootstrap` first.\n"
        )
        sys.exit(1)
    print(f"updating {SRC_DIR}")
    rc = subprocess.run(
        ["git", "-C", str(SRC_DIR), "pull", "--ff-only"], check=False,
    ).returncode
    if rc != 0:
        sys.stderr.write(f"git pull failed (exit={rc})\n")
        sys.exit(1)
    print(f"  ✓ updated {SRC_DIR}")
    return {"status": "updated", "src": str(SRC_DIR)}


# ─── Index ──────────────────────────────────────────────────────────


def cmd_index(args) -> dict:
    """Incremental index — sha-deduped per file."""
    src = Path(args.src) if getattr(args, "src", None) else SRC_DIR
    if not src.exists():
        sys.stderr.write(
            f"source dir not found: {src}\n"
            f"  run: claude_docs_index bootstrap   (clones {REPO_URL})\n"
            f"  or set KAIZEN_CLAUDE_DOCS_SRC to a local docs dir.\n"
        )
        sys.exit(1)
    conn = open_db()
    backend = _kz_embed.resolve_backend()
    active_model = backend.get("model", DEFAULT_MODEL)
    set_meta(conn, "model", active_model)
    set_meta(conn, "backend_kind", backend.get("kind", "local"))
    set_meta(conn, "src", str(src))

    files = list(iter_md_files(src))
    if not files:
        return {"indexed": 0, "skipped": 0, "removed": 0, "total_files": 0, "total_chunks": 0}

    seen_paths: set[str] = set()
    new_count = 0
    skip_count = 0
    chunk_count = 0
    bar = _Progress("claude-docs", total=len(files))
    for path in files:
        rel = str(path.relative_to(src))
        seen_paths.add(rel)
        raw = path.read_bytes()
        sha = file_sha(raw)
        existing = conn.execute(
            "SELECT sha FROM claude_doc_files WHERE path = ?", (rel,),
        ).fetchone()
        if existing and existing["sha"] == sha:
            skip_count += 1
            bar.tick(f"skip {rel}")
            continue
        text = raw.decode("utf-8", errors="replace")
        title = first_h1(text) or path.stem
        chunks = _kz_chunk.chunk_text(text)
        if not chunks:
            bar.tick(f"empty {rel}")
            continue
        chunk_texts = _kz_chunk.apply_passage_prefix_batch([c.text for c in chunks])
        emb_blobs, dim = _kz_embed.embed_batch(chunk_texts)
        # Wipe old chunks for this file (FK cascade may not be enabled).
        conn.execute("DELETE FROM claude_doc_chunks WHERE path = ?", (rel,))
        conn.execute(
            """INSERT OR REPLACE INTO claude_doc_files
               (path, sha, chunk_count, title, bytes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rel, sha, len(chunks), title, len(raw), _now()),
        )
        conn.executemany(
            """INSERT INTO claude_doc_chunks
               (path, chunk_idx, char_start, char_end, section, text, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (rel, c.chunk_idx, c.char_start, c.char_end,
                 nearest_section(text, c.char_start), c.text, blob)
                for c, blob in zip(chunks, emb_blobs)
            ],
        )
        chunk_count += len(chunks)
        new_count += 1
        bar.tick(f"+ {rel} ({len(chunks)} chunks)")
    # Stale removal (files present in db but no longer in src).
    in_db = [r["path"] for r in conn.execute("SELECT path FROM claude_doc_files")]
    stale = [p for p in in_db if p not in seen_paths]
    for p in stale:
        conn.execute("DELETE FROM claude_doc_chunks WHERE path = ?", (p,))
        conn.execute("DELETE FROM claude_doc_files WHERE path = ?", (p,))
    bar.done(f"{new_count} new, {skip_count} skipped, {len(stale)} stale removed")

    set_meta(conn, "last_indexed_ts", _now())
    set_meta(conn, "dim", str(dim if new_count else DEFAULT_DIM))
    total_files = conn.execute("SELECT COUNT(*) FROM claude_doc_files").fetchone()[0]
    total_chunks = conn.execute("SELECT COUNT(*) FROM claude_doc_chunks").fetchone()[0]
    set_meta(conn, "total_files", str(total_files))
    set_meta(conn, "total_chunks", str(total_chunks))
    conn.commit()
    conn.close()
    return {
        "indexed": new_count,
        "skipped": skip_count,
        "removed": len(stale),
        "total_files": total_files,
        "total_chunks": total_chunks,
        "model": active_model,
        "db": str(DB_PATH),
    }


def cmd_reindex(args) -> dict:
    """Drop tables + rebuild from scratch."""
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        conn.executescript(
            "DROP TABLE IF EXISTS claude_doc_chunks; "
            "DROP TABLE IF EXISTS claude_doc_files; "
            "DROP TABLE IF EXISTS claude_doc_meta;"
        )
        conn.commit(); conn.close()
    return cmd_index(args)


# ─── Search ─────────────────────────────────────────────────────────


def do_search(query: str, top_k: int = 8) -> list[dict]:
    """Programmatic search — returns ranked chunks. Used by both the CLI
    (`cmd_search`) and the MCP server (`claude_docs_mcp.py`).

    M6: scoring/embed/dim-filter loop lives in `_search.cosine_topk`.
    claude_docs is the odd one out — it embeds the query with the
    `search_document:` (passage) prefix instead of `search_query:`, so
    we pre-apply via `_kz_chunk.apply_passage_prefix` before passing
    through; the shared helper's `apply_query_prefix=False` keeps it
    from double-prefixing."""
    if not DB_PATH.exists():
        return []
    import _search as _kz_search

    conn = open_db(create=False)
    q_with_prefix = _kz_chunk.apply_passage_prefix(query)
    scored = _kz_search.cosine_topk(
        conn, "claude_doc_chunks", q_with_prefix,
        top_k=top_k,
        select_cols="id, path, chunk_idx, section, text, embedding",
    )
    results = []
    for r, sim in scored:
        snippet = r["text"][:240].replace("\n", " ")
        results.append({
            "id": r["id"],
            "score": round(sim, 4),
            "path": r["path"],
            "chunk_idx": r["chunk_idx"],
            "section": r["section"],
            "snippet": snippet,
        })
    return results


def do_stats() -> dict:
    """Programmatic stats — returns the meta dict. Used by MCP + CLI."""
    if not DB_PATH.exists():
        return {"exists": False, "db": str(DB_PATH)}
    conn = open_db(create=False)
    f = conn.execute("SELECT COUNT(*) FROM claude_doc_files").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM claude_doc_chunks").fetchone()[0]
    return {
        "exists": True,
        "db": str(DB_PATH),
        "src": get_meta(conn, "src", str(SRC_DIR)),
        "model": get_meta(conn, "model", DEFAULT_MODEL),
        "dim": int(get_meta(conn, "dim", str(DEFAULT_DIM))),
        "backend_kind": get_meta(conn, "backend_kind", "local"),
        "files": f,
        "chunks": c,
        "last_indexed_ts": get_meta(conn, "last_indexed_ts", ""),
        "size_bytes": DB_PATH.stat().st_size,
    }


def do_get(chunk_id: int) -> dict | None:
    """Programmatic single-chunk fetch by id. Returns None if absent."""
    if not DB_PATH.exists():
        return None
    conn = open_db(create=False)
    row = conn.execute(
        "SELECT * FROM claude_doc_chunks WHERE id = ?", (chunk_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "path": row["path"],
        "chunk_idx": row["chunk_idx"],
        "char_start": row["char_start"],
        "char_end": row["char_end"],
        "section": row["section"],
        "text": row["text"],
    }


def do_list_files(limit: int = 200) -> list[dict]:
    """Programmatic file listing — returns the file index (no embeddings)."""
    if not DB_PATH.exists():
        return []
    conn = open_db(create=False)
    rows = conn.execute(
        "SELECT path, sha, chunk_count, title, bytes, updated_at FROM claude_doc_files "
        "ORDER BY path LIMIT ?", (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def cmd_search(args) -> dict:
    if not DB_PATH.exists():
        sys.stderr.write("claude-docs: index not built. Run: kaizen-claude-docs index\n")
        sys.exit(1)
    results = do_search(args.query, top_k=args.top_k)
    if getattr(args, "json", False):
        _emit({"query": args.query, "results": results},
              counts={"results": len(results)})
    else:
        for r in results:
            print(f"{r['score']:.3f}  {r['path']}#chunk{r['chunk_idx']}  [{r['section'] or '-'}]")
            print(f"        {r['snippet']}…")
    return {"query": args.query, "count": len(results), "results": results}


# ─── Inspection helpers ─────────────────────────────────────────────


def cmd_stats(args) -> dict:
    out = do_stats()
    _emit(out)
    return out


def cmd_get(args) -> dict:
    out = do_get(args.id)
    if out is None:
        sys.stderr.write(f"no chunk id={args.id}\n"); sys.exit(1)
    _emit(out)
    return out


def cmd_path(args) -> str:
    print(DB_PATH); return str(DB_PATH)


def cmd_clear(args) -> dict:
    """Remove the DB. Pre-deletion belief: this is destructive — require --yes."""
    if not args.yes:
        sys.stderr.write(
            f"clear: refuse without --yes  ({DB_PATH})\n"
            f"  use `claude_docs_index clear --yes` to confirm.\n"
        )
        sys.exit(1)
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"  ✓ removed {DB_PATH}")
    else:
        print(f"  ∘ already gone: {DB_PATH}")
    return {"removed": str(DB_PATH)}


from _time import iso  # M5 dedup


def _now() -> str:
    return iso(precision="seconds")


# ─── CLI (M7: thin IndexerCLI subclass) ─────────────────────────────


from _indexer_cli import IndexerCLI  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-claude-docs", tool_version="1.0.0")


class ClaudeDocsCLI(IndexerCLI):
    PROG = "claude_docs_index"
    DESCRIPTION = __doc__
    DB_PATH = DB_PATH
    SUBCOMMAND_REQUIRED = False  # bare invocation defaults to `stats`

    # Module-level cmd_* already handle their own printing; override the
    # base's cmd_* to delegate directly (avoids double-print + preserves
    # back-compat with the MCP, which imports cmd_index by name).
    def cmd_stats(self, args): cmd_stats(args)
    def cmd_get(self, args): cmd_get(args)
    def cmd_search(self, args): cmd_search(args)
    def cmd_index(self, args): cmd_index(args)
    def cmd_reindex(self, args): cmd_reindex(args)
    def cmd_clear(self, args): cmd_clear(args)

    # do_* stays as the canonical data-returning surface (used by MCP).
    def do_stats(self, args): return do_stats()
    def do_get(self, args): return do_get(args.id)
    def do_search(self, args): return do_search(args.query, top_k=args.top_k)
    def do_index(self, args): return None
    def do_reindex(self, args): return None

    def extra_index_args(self, p):
        p.add_argument("--src", default=None,
                       help="override SRC_DIR for this run")

    def extra_reindex_args(self, p):
        p.add_argument("--src", default=None)

    def extra_clear_args(self, p):
        p.add_argument("--yes", action="store_true")

    def extra_search_args(self, p):
        # Override base's --top-k default of 10 → 8 (claude_docs convention).
        # argparse can't redefine, so reach into the action and tweak.
        for action in p._actions:
            if action.dest == "top_k":
                action.default = 8

    def register_extra_subcommands(self, sub):
        sub.add_parser("bootstrap", help="git clone the upstream docs repo") \
            .set_defaults(func=lambda args: cmd_bootstrap(args))
        sub.add_parser("update", help="git pull the upstream docs repo") \
            .set_defaults(func=lambda args: cmd_update(args))


def main():
    cli = ClaudeDocsCLI()
    parser = cli.build_parser()
    argv = sys.argv[1:] or ["stats"]
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
