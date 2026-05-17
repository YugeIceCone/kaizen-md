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
"""kaizen knowledge-index — SQLite-backed semantic search over kaizen's
non-trace knowledge sources (brain notes, plans, backlog, schemas, persona).

Sibling of `trace_index.py` (which indexes trace events). Same model
(`all-MiniLM-L6-v2`, 384-dim), same SQLite pattern, same privacy
defaults (signature embedded by default; body opt-in via --embed-body).

## Sources

- **brain-note**:  `<KAIZEN_BRAIN_DIR>/Notes/*.md` (Remember Second Brain notes,
                   YAML-frontmatter with `type:` and `tags:`)
- **plan**:        `<repo>/plans/**/*.md` AND `<repo>/plans/archive/**/*.md`
- **backlog**:     `<repo>/.workflow/backlog.json` items (BK-N entries)
- **schema**:      built-in (`<plugin>/schemas/*/schema.yaml`),
                   user (`~/.claude/kaizen-schemas/*/schema.yaml`),
                   project (`<repo>/.workflow/schemas/*/schema.yaml`)
- **persona**:     `<KAIZEN_BRAIN_DIR>/Persona.md` Top Beliefs (one item per belief)
- **arch-log**:    `<repo>/.kaizen/workflow/progress.md` AND
                   `<repo>/.kaizen/workflow/archive/*.md` — one item per row
                   in the architecture-log markdown table. Lets agents query
                   historical structural rows without reading the whole file.

## Privacy

By default, ONLY a signature is embedded: title + tags + source_path
(no body content). Opt-in via `--embed-body` to include the snippet
(first ~400 chars of body). NEVER embeds files matching `*secret*`,
`*credential*`, `*token*` (skipped entirely regardless of flag).

## SQLite schema

    knowledge_items:
        id            INTEGER PRIMARY KEY AUTOINCREMENT
        source        TEXT NOT NULL     -- brain-note | plan | backlog | schema | persona | arch-log
        source_path   TEXT NOT NULL     -- abs path, or BK-N for backlog items
        title         TEXT NOT NULL
        snippet       TEXT              -- first ~400 chars of body
        tags          TEXT              -- JSON list, may be empty
        body_embedded INTEGER NOT NULL  -- 0 or 1
        embedding     BLOB              -- np.float32 array, dim=384
        updated_at    TEXT              -- mtime or backlog updated_at
        sha           TEXT UNIQUE       -- content hash for de-dup

    knowledge_meta:
        key           TEXT PRIMARY KEY
        value         TEXT

## Subcommands

    index [--embed-body]          incremental index (sha-deduped, skips unchanged)
    reindex                       wipe + full rebuild
    search "<query>"              semantic search; flags below
        [--top-k 10] [--source S] [--json]
    stats                         counts by source, model, latest indexed
    get <id>                      fetch one item by id
    path                          print db path
    clear                         drop db

## Env

    KAIZEN_BRAIN_DIR              override brain path (default ~/.claude/.kaizen/brain)
    KAIZEN_KNOWLEDGE_DB           override db path (default ~/.claude/.kaizen-knowledge/index.db)
    KAIZEN_KNOWLEDGE_EMBED_MODEL  override model (default all-MiniLM-L6-v2)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))

# v1.22.0+: paths come from the shared _paths module (config.py is the SSOT).
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import _paths as _p  # noqa: E402
import config as _cfg  # noqa: E402

BRAIN_PATH = _p.BRAIN_DIR
DB_PATH = _p.KNOWLEDGE_DB
DEFAULT_MODEL = os.environ.get("KAIZEN_KNOWLEDGE_EMBED_MODEL", _cfg.EMBED_MODEL)
DEFAULT_DIM = _cfg.EMBED_DIM

PLUGIN_BUILTIN_SCHEMAS = (
    Path(__file__).resolve().parent.parent.parent.parent / "schemas"
)
USER_SCHEMAS_DIR = _p.USER_SCHEMAS
# Resolved at call time (cwd-relative); iter_schemas re-evaluates each call.
def _project_schemas_dir() -> Path:
    return _p.project_schemas_dir()

PRIVACY_SKIP_PATTERNS = (
    re.compile(r"secret", re.I),
    re.compile(r"credential", re.I),
    re.compile(r"token", re.I),
)


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
                f"kaizen-knowledge-index: missing dep: {e}\n"
                "PEP 723 should auto-install via uv. If running with python3:\n"
                "  pip install --user sentence-transformers numpy\n"
            )
            sys.exit(1)
        _np = np
        _model = SentenceTransformer(DEFAULT_MODEL)
    return _model, _np


# ─── SQLite helpers (M1 — shared base in _sqlite.py) ─────────────────


import _sqlite as _kz_sqlite  # noqa: E402

_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS knowledge_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_path TEXT NOT NULL,
        title TEXT NOT NULL,
        snippet TEXT,
        tags TEXT,
        body_embedded INTEGER NOT NULL DEFAULT 0,
        embedding BLOB,
        updated_at TEXT,
        sha TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_source ON knowledge_items(source);
    CREATE INDEX IF NOT EXISTS idx_path ON knowledge_items(source_path);
    CREATE TABLE IF NOT EXISTS knowledge_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
"""


def open_db(create: bool = True) -> sqlite3.Connection:
    return _kz_sqlite.open_indexer_db(DB_PATH, _SCHEMA_SQL, create=create)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    _kz_sqlite.set_meta(conn, "knowledge_meta", key, value)


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    return _kz_sqlite.get_meta(conn, "knowledge_meta", key, default)


# ─── Privacy filter ──────────────────────────────────────────────────


def _should_skip(path: Path) -> bool:
    s = str(path)
    return any(p.search(s) for p in PRIVACY_SKIP_PATTERNS)


# ─── Frontmatter parsing (reusable across sources) ───────────────────


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Flat-scalar yaml only (matches kaizen rules.py)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    for line in m.group(1).split("\n"):
        ln = line.strip()
        if not ln or ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [
                x.strip().strip("'\"")
                for x in v[1:-1].split(",")
                if x.strip()
            ]
        else:
            if (len(v) >= 2) and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            fm[k] = v
    body = text[m.end():]
    return fm, body


def first_h1(body: str) -> str:
    for line in body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def snippet_of(body: str, n: int = 400) -> str:
    stripped = re.sub(r"\s+", " ", body).strip()
    return stripped[:n]


# ─── Source iterators ────────────────────────────────────────────────


def iter_brain_notes():
    notes_dir = BRAIN_PATH / "Notes"
    if not notes_dir.is_dir():
        return
    for f in sorted(notes_dir.glob("*.md")):
        if f.name.endswith(".disabled") or _should_skip(f):
            continue
        try:
            text = f.read_text()
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        title = fm.get("name") or fm.get("description", "")[:60] or f.stem
        snippet = snippet_of(body)
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        yield {
            "source": "brain-note",
            "source_path": str(f),
            "title": title,
            "snippet": snippet,
            "tags": tags,
            "updated_at": dt.datetime.fromtimestamp(
                f.stat().st_mtime, dt.timezone.utc
            ).isoformat(),
        }


def iter_plans():
    plans_dir = Path.cwd() / "plans"
    if not plans_dir.is_dir():
        return
    for f in plans_dir.rglob("*.md"):
        if _should_skip(f):
            continue
        try:
            text = f.read_text()
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        title = first_h1(body) or f.stem
        snippet = snippet_of(body)
        yield {
            "source": "plan",
            "source_path": str(f),
            "title": title,
            "snippet": snippet,
            "tags": [],
            "updated_at": dt.datetime.fromtimestamp(
                f.stat().st_mtime, dt.timezone.utc
            ).isoformat(),
        }


def iter_backlog_items():
    bf = _p.project_workflow_dir() / "backlog.json"
    if not bf.is_file():
        return
    try:
        data = json.loads(bf.read_text())
    except (OSError, json.JSONDecodeError):
        return
    items = data.get("items") or data.get("backlog") or []
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        bid = item.get("id") or item.get("BK") or ""
        title = item.get("title") or ""
        if not (bid and title):
            continue
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        probe = item.get("probe") or ""
        verify = item.get("verify") or ""
        snippet = f"probe: {probe}\nverify: {verify}".strip()
        yield {
            "source": "backlog",
            "source_path": f"{bid} ({bf})",
            "title": f"{bid} {title}".strip(),
            "snippet": snippet_of(snippet),
            "tags": tags,
            "updated_at": item.get("updated_at") or item.get("created_at") or "",
        }


def iter_schemas():
    for base in (_project_schemas_dir(), USER_SCHEMAS_DIR, PLUGIN_BUILTIN_SCHEMAS):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            schema_path = entry / "schema.yaml"
            if not (entry.is_dir() and schema_path.is_file()):
                continue
            try:
                text = schema_path.read_text()
            except OSError:
                continue
            name_match = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
            desc_match = re.search(
                r"^description:\s*\|\s*\n((?:[ \t]+.+\n?)+)", text, re.MULTILINE
            )
            title = name_match.group(1).strip() if name_match else entry.name
            desc = (
                "\n".join(line.strip() for line in desc_match.group(1).split("\n"))
                if desc_match
                else ""
            )
            yield {
                "source": "schema",
                "source_path": str(schema_path),
                "title": f"schema:{title}",
                "snippet": snippet_of(desc),
                "tags": [],
                "updated_at": dt.datetime.fromtimestamp(
                    schema_path.stat().st_mtime, dt.timezone.utc
                ).isoformat(),
            }


def iter_persona_beliefs():
    pf = BRAIN_PATH / "Persona.md"
    if not pf.is_file():
        return
    try:
        text = pf.read_text()
    except OSError:
        return
    # Find ## Top Beliefs section and split per-belief lines.
    m = re.search(
        r"^##\s+Top Beliefs\s*\n(.+?)(?=\n^##\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return
    block = m.group(1)
    for line in block.split("\n"):
        ln = line.strip()
        if not ln or not ln.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
            continue
        if "[[" in ln and "]]" in ln:
            ref = ln[ln.find("[[") + 2 : ln.find("]]")]
        else:
            ref = ln
        yield {
            "source": "persona",
            "source_path": str(pf),
            "title": f"belief: {ref[:60]}",
            "snippet": snippet_of(ln),
            "tags": ["persona", "belief"],
            "updated_at": dt.datetime.fromtimestamp(
                pf.stat().st_mtime, dt.timezone.utc
            ).isoformat(),
        }


def iter_arch_log():
    """Yield one item per row from `<repo>/.kaizen/workflow/progress.md` and
    `<repo>/.kaizen/workflow/archive/*.md`. Each row in the markdown table
    becomes a separately indexed knowledge item, so agents can query
    historical scope tags (e.g. "§F2.2", "F-FINAL deletion gate") without
    reading the whole file.

    Row format expected: `| date | scope | Δ LOC | summary |`
    """
    arch_dir = Path.cwd() / ".kaizen" / "workflow"
    if not arch_dir.is_dir():
        return

    files: list[Path] = []
    live = arch_dir / "progress.md"
    if live.is_file():
        files.append(live)
    archive_dir = arch_dir / "archive"
    if archive_dir.is_dir():
        files.extend(sorted(archive_dir.glob("*.md")))

    for f in files:
        try:
            text = f.read_text()
        except OSError:
            continue
        mtime_iso = dt.datetime.fromtimestamp(
            f.stat().st_mtime, dt.timezone.utc
        ).isoformat()
        for raw in text.splitlines():
            line = raw.strip()
            # Match data rows only: `| YYYY-MM-DD | scope | … | summary |`
            if not line.startswith("| 20") or "|---" in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            date, scope, delta_loc, summary = cells[0], cells[1], cells[2], cells[3]
            if not summary:
                continue
            yield {
                "source": "arch-log",
                "source_path": f"{f}#{date}-{scope}",
                "title": f"{date} {scope}: {summary[:80]}",
                "snippet": f"date: {date}\nscope: {scope}\nΔ LOC: {delta_loc}\n{summary}",
                "tags": ["arch-log", scope] if scope else ["arch-log"],
                "updated_at": mtime_iso,
            }


def iter_all_sources():
    yield from iter_brain_notes()
    yield from iter_plans()
    yield from iter_backlog_items()
    yield from iter_schemas()
    yield from iter_persona_beliefs()
    yield from iter_arch_log()


# ─── Item identity + embedding ───────────────────────────────────────


def item_sha(item: dict) -> str:
    """Stable identity hash. Source + path + title + updated_at."""
    s = f"{item['source']}|{item['source_path']}|{item['title']}|{item['updated_at']}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def item_to_text(item: dict, embed_body: bool) -> str:
    """Build the embeddable signature. Privacy-safe by default."""
    bits = [
        f"source: {item['source']}",
        f"title: {item['title']}",
    ]
    tags = item.get("tags") or []
    if tags:
        bits.append(f"tags: {', '.join(tags)}")
    if embed_body and item.get("snippet"):
        bits.append(f"body: {item['snippet']}")
    return " | ".join(bits)


import _embed as _kz_embed  # v1.25.0+: HTTP-first embedding backend
from _progress import Progress as _Progress  # v1.30.0+: live stderr progress


def embed_one(text: str):
    # v1.25.0+: routes via _embed (llama-server HTTP first, sentence-transformers fallback).
    blob, _dim = _kz_embed.embed_one(text)
    return blob


# ─── Data-returning helpers (also used by knowledge_mcp.py) ──────────


def do_index(embed_body: bool = False) -> dict:
    """Run the incremental index pass. Returns {new, skipped, stale}."""
    conn = open_db(create=True)
    seen_sha: set[str] = set()
    new_count = 0
    skip_count = 0
    all_items = list(iter_all_sources())
    bar = _Progress("knowledge", total=len(all_items))
    for item in all_items:
        sha = item_sha(item)
        seen_sha.add(sha)
        existing = conn.execute(
            "SELECT id, body_embedded FROM knowledge_items WHERE sha = ?", (sha,)
        ).fetchone()
        if existing and (existing["body_embedded"] == int(embed_body)):
            skip_count += 1
            bar.tick(f"skip {item.get('source', '')}/{item.get('title', '')[:30]}")
            continue
        emb = embed_one(item_to_text(item, embed_body))
        conn.execute(
            """INSERT OR REPLACE INTO knowledge_items
               (source, source_path, title, snippet, tags, body_embedded, embedding, updated_at, sha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["source"],
                item["source_path"],
                item["title"],
                item.get("snippet", ""),
                json.dumps(item.get("tags") or []),
                int(embed_body),
                emb,
                item.get("updated_at", ""),
                sha,
            ),
        )
        new_count += 1
        bar.tick(f"+ {item.get('source', '')}/{item.get('title', '')[:30]}")
    bar.done(f"{new_count} new, {skip_count} skipped")
    all_in_db = conn.execute("SELECT sha FROM knowledge_items").fetchall()
    stale = [r["sha"] for r in all_in_db if r["sha"] not in seen_sha]
    if stale:
        conn.executemany(
            "DELETE FROM knowledge_items WHERE sha = ?", [(s,) for s in stale]
        )
    set_meta(conn, "model", DEFAULT_MODEL)
    set_meta(conn, "dim", str(DEFAULT_DIM))
    set_meta(
        conn,
        "last_indexed_ts",
        dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    total = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
    set_meta(conn, "total_items", str(total))
    conn.commit()
    conn.close()
    return {
        "new": new_count,
        "skipped": skip_count,
        "stale_removed": len(stale),
        "total": total,
        "model": DEFAULT_MODEL,
    }


def do_search(
    query: str,
    top_k: int = 10,
    source: str | None = None,
) -> list[dict]:
    """Cosine-similarity search. Returns [{score, id, source, source_path, title, snippet, tags, updated_at}, ...].

    M6: scoring/embed/dim-filter loop lives in `_search.cosine_topk`."""
    if not DB_PATH.is_file():
        return []
    import _search as _kz_search

    conn = open_db(create=False)
    where = "source = ?" if source else ""
    params: list = [source] if source else []
    scored = _kz_search.cosine_topk(
        conn, "knowledge_items", query,
        top_k=top_k,
        where=where,
        params=params,
    )
    out = []
    for r, score in scored:
        out.append(
            {
                "score": round(score, 4),
                "id": r["id"],
                "source": r["source"],
                "source_path": r["source_path"],
                "title": r["title"],
                "snippet": r["snippet"],
                "tags": json.loads(r["tags"] or "[]"),
                "updated_at": r["updated_at"],
            }
        )
    conn.close()
    return out


def do_stats() -> dict:
    """Return index stats as a dict. Caller decides how to render."""
    if not DB_PATH.is_file():
        return {"indexed": False, "db_path": str(DB_PATH)}
    conn = open_db(create=False)
    out = {
        "indexed": True,
        "db_path": str(DB_PATH),
        "model": get_meta(conn, "model", ""),
        "dim": get_meta(conn, "dim", ""),
        "last_indexed_ts": get_meta(conn, "last_indexed_ts", ""),
        "total": conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0],
    }
    by_source = {}
    for r in conn.execute(
        "SELECT source, COUNT(*) AS n FROM knowledge_items GROUP BY source"
    ).fetchall():
        by_source[r["source"]] = r["n"]
    out["by_source"] = by_source
    conn.close()
    return out


def do_get(item_id: int) -> dict | None:
    """Return one item record by id (no embedding bytes), or None if missing."""
    if not DB_PATH.is_file():
        return None
    conn = open_db(create=False)
    r = conn.execute(
        "SELECT * FROM knowledge_items WHERE id = ?", (item_id,)
    ).fetchone()
    conn.close()
    if not r:
        return None
    out = {k: r[k] for k in r.keys() if k != "embedding"}
    out["tags"] = json.loads(out.get("tags") or "[]")
    return out


# ─── CLI (M7: thin IndexerCLI subclass) ──────────────────────────────


from _indexer_cli import IndexerCLI  # noqa: E402


class KnowledgeCLI(IndexerCLI):
    PROG = "kaizen-knowledge-index"
    DESCRIPTION = (
        "Semantic search over brain notes, plans, backlog, schemas, persona."
    )
    DB_PATH = DB_PATH

    def do_stats(self, args):
        return do_stats()

    def do_get(self, args):
        return do_get(args.id)

    def do_search(self, args):
        return do_search(args.query, top_k=args.top_k, source=args.source)

    def do_index(self, args):
        result = do_index(embed_body=args.embed_body)
        return result

    def do_clear(self, args):
        if DB_PATH.is_file():
            DB_PATH.unlink()
            print(f"kaizen-knowledge: cleared {DB_PATH}", file=sys.stderr)
        else:
            print("kaizen-knowledge: no index to clear", file=sys.stderr)
        return {"removed": str(DB_PATH) if not DB_PATH.exists() else None}

    def extra_index_args(self, p):
        p.add_argument(
            "--embed-body",
            action="store_true",
            help="also embed snippet body (privacy: defaults to signature only)",
        )

    def extra_reindex_args(self, p):
        p.add_argument("--embed-body", action="store_true")

    def extra_search_args(self, p):
        p.add_argument(
            "--source",
            choices=["brain-note", "plan", "backlog", "schema", "persona"],
            help="filter results by source type",
        )

    def print_index(self, result, args):
        if not result:
            return
        print(
            f"kaizen-knowledge: indexed {result['new']} new, "
            f"skipped {result['skipped']} unchanged, "
            f"removed {result['stale_removed']} stale",
            file=sys.stderr,
        )

    def print_stats(self, s, args):
        if not s.get("indexed"):
            print("kaizen-knowledge: no index yet — run `index` first")
            return
        print(f"db:        {s['db_path']}")
        print(f"model:     {s.get('model', '?') or '?'}")
        print(f"dim:       {s.get('dim', '?') or '?'}")
        print(f"indexed:   {s.get('last_indexed_ts', '?') or '?'}")
        print(f"total:     {s['total']}")
        for src, n in sorted(
            s["by_source"].items(), key=lambda kv: kv[1], reverse=True
        ):
            print(f"  {src:<12} {n}")

    def print_get(self, r, args):
        if r is None:
            sys.exit(f"id {args.id} not found")
        print(json.dumps(r, indent=2))

    def print_search(self, results, args):
        for r in results:
            tags = r.get("tags") or []
            tag_str = f" [{','.join(tags)}]" if tags else ""
            print(
                f"  {r['score']:.3f}  {r['source']:<10} {r['title']}{tag_str}"
            )
            print(f"           → {r['source_path']}")
            if r["snippet"]:
                print(f"           {r['snippet'][:120]}")

    def print_clear(self, result, args):
        # Already printed in do_clear (preserves original stderr behavior).
        return


def build_parser() -> argparse.ArgumentParser:
    """Back-compat shim — some callers may import this name."""
    return KnowledgeCLI().build_parser()


def main():
    KnowledgeCLI().run()


if __name__ == "__main__":
    main()
