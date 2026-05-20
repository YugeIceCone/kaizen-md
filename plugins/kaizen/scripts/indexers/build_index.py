#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "numpy>=1.24",
#     "sentence-transformers>=2.2",
# ]
# ///
# consolidated-cli-parent: brain

"""kaizen brain index — SQLite + sentence-transformers over the
Second Brain.

Mirrors the trace_index / onboard_index / knowledge_index pattern
but is brain-specific: it preserves typed frontmatter (type,
confidence, sources_count, freshness) so search can filter on
those, not just generic title + body.

## Schema

::

   CREATE TABLE brain_notes (
     id            INTEGER PRIMARY KEY AUTOINCREMENT,
     path          TEXT UNIQUE NOT NULL,
     name          TEXT NOT NULL,
     description   TEXT NOT NULL,
     type          TEXT NOT NULL,             -- world-fact / belief / ...
     confidence    REAL,                       -- belief-only
     tags          TEXT NOT NULL DEFAULT '[]', -- JSON array
     sources_count INTEGER NOT NULL DEFAULT 0,
     freshness     TEXT,                       -- fresh / stable / stale
     subdir        TEXT NOT NULL,              -- Notes / People / Projects / etc.
     embedding     BLOB,
     embedding_q8  BLOB,
     sha           TEXT NOT NULL,
     updated_at    TEXT NOT NULL
   );
   CREATE INDEX idx_brain_type ON brain_notes(type);
   CREATE INDEX idx_brain_subdir ON brain_notes(subdir);
   CREATE INDEX idx_brain_confidence ON brain_notes(confidence);

## Indexing flow (Node+Flow)

   DiscoverNode → WalkNode → EmbedNode → UpsertNode → ReportNode

## CLI

::

   kaizen-build-index index           # build / rebuild
   kaizen-build-index search "<q>"    # semantic + frontmatter filter
     [--type belief|world-fact|observation|experience]
     [--min-confidence 0.7]
     [--subdir Notes|People|...]
   kaizen-build-index stats           # counts per type / freshness
   kaizen-build-index path            # print db path
   kaizen-build-index get <id>        # full note + frontmatter
   kaizen-build-index clear --yes     # drop the db

The index db lives at ``$KAIZEN_BRAIN_DB`` (env) or
``<KAIZEN_USER_DIR>/brain.db`` (default ``~/.claude/.kaizen/brain.db``).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterator, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — until helpers move from skills/workflow/scripts/ → scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "scripts" / "brain"))

import _brain  # noqa: E402
import _sqlite as _kz_sqlite  # noqa: E402  — shared SQLite open/meta helpers
import flow as _flow  # noqa: E402

# ─── Paths ────────────────────────────────────────────────────────────

def _kaizen_user_dir() -> Path:
    return Path("~/.claude/.kaizen").expanduser().resolve()

def db_path() -> Path:
    """Resolve the brain index db path.

    Priority: ``KAIZEN_BRAIN_DB`` env > ``<KAIZEN_USER_DIR>/brain.db``."""
    env = os.environ.get("KAIZEN_BRAIN_DB", "")
    if env:
        return Path(os.path.expandvars(env)).expanduser().resolve()
    return _kaizen_user_dir() / "brain.db"

# ─── Schema ──────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS brain_notes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    type          TEXT NOT NULL,
    confidence    REAL,
    tags          TEXT NOT NULL DEFAULT '[]',
    sources_count INTEGER NOT NULL DEFAULT 0,
    freshness     TEXT,
    subdir        TEXT NOT NULL,
    body          TEXT NOT NULL,
    embedding     BLOB,
    sha           TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_type ON brain_notes(type);
CREATE INDEX IF NOT EXISTS idx_brain_subdir ON brain_notes(subdir);
CREATE INDEX IF NOT EXISTS idx_brain_confidence ON brain_notes(confidence);
CREATE INDEX IF NOT EXISTS idx_brain_freshness ON brain_notes(freshness);

CREATE TABLE IF NOT EXISTS brain_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

def open_db(create: bool = True) -> sqlite3.Connection:
    """Open the brain index db via the shared `_sqlite.open_indexer_db`
    helper — same path onboard_index / trace_index / knowledge_index
    take. (DRY: this module used to reimplement open/schema; the
    self-audit DRY checkpoint flagged the duplication.)"""
    conn = _kz_sqlite.open_indexer_db(db_path(), _SCHEMA_SQL, create=create)
    if create:
        conn.commit()
    return conn

def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Thin wrapper over the shared `_sqlite.set_meta` — pins the
    brain-specific meta table name so callers stay 1-arg."""
    _kz_sqlite.set_meta(conn, "brain_meta", key, value)

def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """Thin wrapper over the shared `_sqlite.get_meta` — pins the
    brain-specific meta table name."""
    return _kz_sqlite.get_meta(conn, "brain_meta", key, default)

# ─── Brain walker ────────────────────────────────────────────────────

# Subdirs under brain_root that we index. Inbox is excluded (it's a
# scratch area for in-progress captures). Archive is excluded (it's a
# deliberate forgetting bin).
_INDEX_SUBDIRS = ("Notes", "Projects", "People", "Areas")

def iter_brain_notes(brain_root: Optional[Path] = None) -> Iterator[dict]:
    """Walk the indexable brain subdirs, yield note records.

    Each record has the frontmatter + body + computed fields the
    schema needs. Files with invalid / missing frontmatter still
    surface — name defaults to the file stem; type defaults to
    world-fact."""
    root = brain_root or _brain.brain_root()
    if not root.is_dir():
        return
    for sub in _INDEX_SUBDIRS:
        d = root / sub
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            if f.name.startswith("."):
                continue
            if f.name.endswith(".disabled"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, body = _brain.parse_note(text)
            yield {
                "path": str(f.resolve()),
                "name": fm.get("name") or f.stem,
                "description": fm.get("description") or "",
                "type": fm.get("type") or "world-fact",
                "confidence": (
                    float(fm["confidence"]) if "confidence" in fm
                    and fm["confidence"] is not None else None
                ),
                "tags": fm.get("tags") or [],
                "sources_count": int(fm.get("sources_count") or 0),
                "freshness": fm.get("freshness"),
                "subdir": sub,
                "body": body.strip(),
                "sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "updated_at": dt.datetime.fromtimestamp(
                    f.stat().st_mtime, dt.timezone.utc
                ).isoformat(),
            }

# ─── Embedding ───────────────────────────────────────────────────────

def _record_text_for_embed(rec: dict) -> str:
    """Concatenate the fields we want the embedding to capture.

    Title + description carry the most signal per token; body adds
    grounding. Tags surfaced inline so tag-based queries match
    semantically too."""
    tags_str = ", ".join(rec["tags"]) if rec.get("tags") else ""
    parts = [
        f"name: {rec.get('name', '')}",
        f"description: {rec.get('description', '')}",
        f"type: {rec.get('type', '')}",
    ]
    if tags_str:
        parts.append(f"tags: {tags_str}")
    if rec.get("body"):
        parts.append(rec["body"][:1200])
    return "\n".join(parts)

def _maybe_embed(text: str):
    """Try the kaizen embed pipeline. Returns (bytes, dim) or
    (None, 0) when no embedding backend is available — search still
    works via LIKE filtering on stored fields.

    Catches BaseException because `_embed.embed_one` calls `sys.exit(1)`
    on missing-numpy (raises SystemExit, which is NOT caught by
    `except Exception`). Without this, build_index crashes and writes
    0 rows — the bug that left brain.db at 0 bytes pre-fix."""
    try:
        import _embed
        return _embed.embed_one(text)
    except BaseException:
        return None, 0

# ─── Flow ────────────────────────────────────────────────────────────

class DiscoverNode(_flow.AsyncNode):
    """Walk brain dirs; produce the candidate record list."""

    async def prep_async(self, store: dict) -> Path:
        return store.get("brain_root") or _brain.brain_root()

    async def exec_async(self, root: Path) -> list:
        return list(iter_brain_notes(root))

    async def post_async(self, store: dict, root: Path, records: list) -> str:
        store["records"] = records
        store["discovered_count"] = len(records)
        return "default"

class EmbedNode(_flow.AsyncNode):
    """Embed each record's compact text. Skip when no backend
    available — search degrades to LIKE."""

    async def prep_async(self, store: dict) -> list:
        return store.get("records") or []

    async def exec_async(self, records: list) -> list:
        if store_skip_embed():
            return [None] * len(records)
        out = []
        for rec in records:
            text = _record_text_for_embed(rec)
            blob, _ = _maybe_embed(text)
            out.append(blob)
        return out

    async def post_async(self, store: dict, records: list, embeddings: list) -> str:
        store["embeddings"] = embeddings
        store["embed_count"] = sum(1 for e in embeddings if e is not None)
        return "default"

def store_skip_embed() -> bool:
    """``KAIZEN_BRAIN_INDEX_SKIP_EMBED=1`` to skip the embedding step
    (text-only search). Useful for fast smoke / CI runs."""
    return os.environ.get("KAIZEN_BRAIN_INDEX_SKIP_EMBED", "").lower() in {"1", "true", "yes"}

class UpsertNode(_flow.AsyncNode):
    """INSERT OR REPLACE the records into brain_notes. Removes rows
    whose path was not seen this run (stale-cleanup)."""

    async def prep_async(self, store: dict) -> dict:
        return {
            "records": store.get("records") or [],
            "embeddings": store.get("embeddings") or [],
        }

    async def exec_async(self, prep: dict) -> dict:
        conn = open_db(create=True)
        try:
            seen_paths: set[str] = set()
            inserted = 0
            updated = 0
            for rec, emb in zip(prep["records"], prep["embeddings"]):
                seen_paths.add(rec["path"])
                row = conn.execute(
                    "SELECT id, sha FROM brain_notes WHERE path = ?",
                    (rec["path"],),
                ).fetchone()
                if row and row["sha"] == rec["sha"]:
                    continue  # unchanged
                conn.execute(
                    """INSERT INTO brain_notes
                       (path, name, description, type, confidence, tags,
                        sources_count, freshness, subdir, body, embedding,
                        sha, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(path) DO UPDATE SET
                           name=excluded.name,
                           description=excluded.description,
                           type=excluded.type,
                           confidence=excluded.confidence,
                           tags=excluded.tags,
                           sources_count=excluded.sources_count,
                           freshness=excluded.freshness,
                           subdir=excluded.subdir,
                           body=excluded.body,
                           embedding=excluded.embedding,
                           sha=excluded.sha,
                           updated_at=excluded.updated_at""",
                    (
                        rec["path"], rec["name"], rec["description"],
                        rec["type"], rec["confidence"],
                        json.dumps(rec["tags"] or []),
                        rec["sources_count"], rec["freshness"],
                        rec["subdir"], rec["body"], emb,
                        rec["sha"], rec["updated_at"],
                    ),
                )
                if row:
                    updated += 1
                else:
                    inserted += 1
            # Stale cleanup
            existing = conn.execute("SELECT path FROM brain_notes").fetchall()
            stale = [r["path"] for r in existing if r["path"] not in seen_paths]
            for p in stale:
                conn.execute("DELETE FROM brain_notes WHERE path = ?", (p,))
            set_meta(
                conn, "last_indexed_ts",
                dt.datetime.now(dt.timezone.utc).isoformat(),
            )
            set_meta(conn, "total_notes", str(
                conn.execute("SELECT COUNT(*) FROM brain_notes").fetchone()[0]
            ))
            conn.commit()
            return {"inserted": inserted, "updated": updated,
                    "removed": len(stale)}
        finally:
            conn.close()

    async def post_async(self, store: dict, prep: dict, exec_result: dict) -> str:
        store["upsert_stats"] = exec_result
        return "default"

class ReportNode(_flow.AsyncNode):
    """Build the final report dict for callers."""

    async def prep_async(self, store: dict) -> None:
        return None

    async def exec_async(self, prep) -> None:
        return None

    async def post_async(self, store: dict, prep, exec_result) -> str:
        upsert = store.get("upsert_stats") or {}
        store["report"] = {
            "db_path": str(db_path()),
            "discovered": store.get("discovered_count", 0),
            "inserted": upsert.get("inserted", 0),
            "updated": upsert.get("updated", 0),
            "removed": upsert.get("removed", 0),
            "embed_count": store.get("embed_count", 0),
        }
        return "default"

def build_index_flow() -> _flow.AsyncFlow:
    discover = DiscoverNode()
    embed = EmbedNode()
    upsert = UpsertNode()
    report = ReportNode()
    f = _flow.AsyncFlow(discover)
    f.add_successor(discover, "default", embed)
    f.add_successor(embed, "default", upsert)
    f.add_successor(upsert, "default", report)
    return f

def do_index(brain_root: Optional[Path] = None) -> dict:
    """Run the indexing flow and return the report."""
    return asyncio.run(_index_async(brain_root))

async def _index_async(brain_root: Optional[Path] = None) -> dict:
    store: dict = {"brain_root": brain_root}
    await build_index_flow().run_async(store)
    return store.get("report") or {}

# ─── Search ──────────────────────────────────────────────────────────

def do_search(
    query: str,
    *,
    top_k: int = 10,
    type_filter: Optional[str] = None,
    subdir_filter: Optional[str] = None,
    min_confidence: Optional[float] = None,
) -> list[dict]:
    """Search the brain index. Returns top_k matches.

    When an embedding backend is available, cosine-rank embeddings.
    Otherwise fall back to a LIKE search over name + description +
    body. Filters apply to BOTH paths.
    """
    conn = open_db(create=False)
    try:
        where_parts = []
        params: list = []
        if type_filter:
            where_parts.append("type = ?")
            params.append(type_filter)
        if subdir_filter:
            where_parts.append("subdir = ?")
            params.append(subdir_filter)
        if min_confidence is not None:
            where_parts.append("confidence >= ?")
            params.append(float(min_confidence))
        where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # Try semantic first
        try:
            import _embed
            import numpy as np
            qblob, _ = _embed.embed_one(query)
            qvec = np.frombuffer(qblob, dtype=np.float32)
            qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)
            rows = conn.execute(
                f"SELECT id, name, description, type, confidence, tags, "
                f"sources_count, freshness, subdir, path, embedding "
                f"FROM brain_notes{where} AND embedding IS NOT NULL"
                if where
                else "SELECT id, name, description, type, confidence, tags, "
                "sources_count, freshness, subdir, path, embedding "
                "FROM brain_notes WHERE embedding IS NOT NULL",
                params,
            ).fetchall()
            scored = []
            for r in rows:
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                if vec.shape != qvec.shape:
                    continue
                v_norm = vec / (np.linalg.norm(vec) + 1e-12)
                score = float(qnorm @ v_norm)
                scored.append((score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [_row_to_dict(r, score=s) for s, r in scored[:top_k]]
        except Exception:
            pass

        # Text fallback — LIKE over name+description+body
        like = f"%{query}%"
        like_params = params + [like, like, like]
        rows = conn.execute(
            f"SELECT id, name, description, type, confidence, tags, "
            f"sources_count, freshness, subdir, path "
            f"FROM brain_notes{where} AND (name LIKE ? OR description LIKE ? "
            f"OR body LIKE ?) LIMIT ?"
            if where
            else "SELECT id, name, description, type, confidence, tags, "
            "sources_count, freshness, subdir, path "
            "FROM brain_notes WHERE (name LIKE ? OR description LIKE ? "
            "OR body LIKE ?) LIMIT ?",
            like_params + [top_k],
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()

def _row_to_dict(r: sqlite3.Row, score: Optional[float] = None) -> dict:
    d = {k: r[k] for k in r.keys() if k != "embedding"}
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except json.JSONDecodeError:
        d["tags"] = []
    if score is not None:
        d["score"] = round(score, 4)
    return d

def do_stats() -> dict:
    """Stats: total / per-type / per-subdir / per-freshness."""
    conn = open_db(create=False)
    try:
        total = conn.execute("SELECT COUNT(*) FROM brain_notes").fetchone()[0]
        by_type = dict(conn.execute(
            "SELECT type, COUNT(*) FROM brain_notes GROUP BY type"
        ).fetchall())
        by_subdir = dict(conn.execute(
            "SELECT subdir, COUNT(*) FROM brain_notes GROUP BY subdir"
        ).fetchall())
        by_freshness = dict(conn.execute(
            "SELECT COALESCE(freshness, 'unset'), COUNT(*) "
            "FROM brain_notes GROUP BY freshness"
        ).fetchall())
        last_indexed = get_meta(conn, "last_indexed_ts", "")
        return {
            "db_path": str(db_path()),
            "total": total,
            "by_type": by_type,
            "by_subdir": by_subdir,
            "by_freshness": by_freshness,
            "last_indexed_ts": last_indexed,
        }
    finally:
        conn.close()

def do_get(item_id: int) -> Optional[dict]:
    conn = open_db(create=False)
    try:
        r = conn.execute(
            "SELECT * FROM brain_notes WHERE id = ?", (item_id,),
        ).fetchone()
        return _row_to_dict(r) if r else None
    finally:
        conn.close()

def do_clear() -> dict:
    p = db_path()
    if p.is_file():
        p.unlink()
        return {"cleared": True, "path": str(p)}
    return {"cleared": False, "path": str(p)}

# ─── CLI (thin IndexerCLI subclass — alignment with the other 6 indexers) ───

from _indexer_cli import IndexerCLI  # noqa: E402

class BuildIndexCLI(IndexerCLI):
    """Build the Second Brain's SQLite + sentence-transformers index.

    Subclasses ``_indexer_cli.IndexerCLI`` so the 6-subcommand shape
    (index/search/stats/get/path/clear) matches onboard / knowledge /
    claude_docs / scrape / trace / loc. Reindex is intentionally NOT
    exposed (no prior contract for it; preserves user-facing API)."""

    PROG = "kaizen-build-index"
    DESCRIPTION = "Index + search the kaizen Second Brain."
    STANDARD_SUBCOMMANDS = ("index", "search", "stats", "get", "path", "clear")

    def db_path_for(self, args):
        # Env-resolved each call — KAIZEN_BRAIN_DB wins over default.
        return db_path()

    def do_stats(self, args):
        return do_stats()

    def do_get(self, args):
        return do_get(args.id)

    def do_search(self, args):
        return do_search(
            args.query,
            top_k=args.top_k,
            type_filter=args.type,
            subdir_filter=args.subdir,
            min_confidence=args.min_confidence,
        )

    def do_index(self, args):
        return do_index()

    def extra_search_args(self, p):
        p.add_argument(
            "--type",
            choices=["world-fact", "belief", "observation", "experience"],
        )
        p.add_argument("--subdir", choices=list(_INDEX_SUBDIRS))
        p.add_argument("--min-confidence", type=float)

    def extra_clear_args(self, p):
        p.add_argument("--yes", action="store_true", required=False)

    # ─── Output-shape overrides (preserve prior JSON contracts) ──────

    def cmd_path(self, args):
        # Prior shape: {"db_path": "..."} JSON object (vs default raw print).
        print(json.dumps({"db_path": str(self.db_path_for(args))}, indent=2))

    def cmd_get(self, args):
        # Prior shape: {"error": "id N not found"} + rc=1 on missing.
        out = self.do_get(args)
        if out is None:
            print(json.dumps({"error": f"id {args.id} not found"}))
            sys.exit(1)
        print(json.dumps(out, indent=2))

    def cmd_clear(self, args):
        # Prior contract: --yes required; emit {"cleared": bool, "path": "..."}.
        if not args.yes:
            print("Refusing to clear without --yes", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(do_clear(), indent=2))

def main(argv: Optional[list[str]] = None) -> int:
    BuildIndexCLI().run(argv)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
