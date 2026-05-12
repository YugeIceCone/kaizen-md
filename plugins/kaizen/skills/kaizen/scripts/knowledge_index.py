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

- **brain-note**:  `<KAIZEN_BRAIN>/Notes/*.md` (Remember Second Brain notes,
                   YAML-frontmatter with `type:` and `tags:`)
- **plan**:        `<repo>/plans/**/*.md` AND `<repo>/plans/archive/**/*.md`
- **backlog**:     `<repo>/.workflow/backlog.json` items (BK-N entries)
- **schema**:      built-in (`<plugin>/schemas/*/schema.yaml`),
                   user (`~/.claude/kaizen-schemas/*/schema.yaml`),
                   project (`<repo>/.workflow/schemas/*/schema.yaml`)
- **persona**:     `<KAIZEN_BRAIN>/Persona.md` Top Beliefs (one item per belief)

## Privacy

By default, ONLY a signature is embedded: title + tags + source_path
(no body content). Opt-in via `--embed-body` to include the snippet
(first ~400 chars of body). NEVER embeds files matching `*secret*`,
`*credential*`, `*token*` (skipped entirely regardless of flag).

## SQLite schema

    knowledge_items:
        id            INTEGER PRIMARY KEY AUTOINCREMENT
        source        TEXT NOT NULL     -- brain-note | plan | backlog | schema | persona
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

    KAIZEN_BRAIN                  override brain path (default ~/.claude/brain)
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
BRAIN_PATH = Path(os.environ.get("KAIZEN_BRAIN", HOME / ".claude" / "brain"))
DB_PATH = Path(
    os.environ.get(
        "KAIZEN_KNOWLEDGE_DB",
        HOME / ".claude" / ".kaizen-knowledge" / "index.db",
    )
)
DEFAULT_MODEL = os.environ.get("KAIZEN_KNOWLEDGE_EMBED_MODEL", "all-MiniLM-L6-v2")
DEFAULT_DIM = 384

PLUGIN_BUILTIN_SCHEMAS = (
    Path(__file__).resolve().parent.parent.parent.parent / "schemas"
)
USER_SCHEMAS_DIR = HOME / ".claude" / "kaizen-schemas"
PROJECT_SCHEMAS_DIR = Path.cwd() / ".workflow" / "schemas"

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


# ─── SQLite helpers ──────────────────────────────────────────────────


def open_db(create: bool = True) -> sqlite3.Connection:
    if create:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if create:
        conn.executescript(
            """
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
        )
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO knowledge_meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM knowledge_meta WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


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
    bf = Path.cwd() / ".workflow" / "backlog.json"
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
    for base in (PROJECT_SCHEMAS_DIR, USER_SCHEMAS_DIR, PLUGIN_BUILTIN_SCHEMAS):
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


def iter_all_sources():
    yield from iter_brain_notes()
    yield from iter_plans()
    yield from iter_backlog_items()
    yield from iter_schemas()
    yield from iter_persona_beliefs()


# ─── Item identity + embedding ───────────────────────────────────────


def item_sha(item: dict) -> str:
    """Stable identity hash. Source + path + title + updated_at."""
    s = f"{item['source']}|{item['source_path']}|{item['title']}|{item['updated_at']}"
    return hashlib.sha1(s.encode()).hexdigest()[:16]


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


def embed_one(text: str):
    model, np = _load_model()
    vec = model.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return vec.astype(np.float32).tobytes()


# ─── Index command ───────────────────────────────────────────────────


def cmd_index(args):
    conn = open_db(create=True)
    seen_sha: set[str] = set()
    new_count = 0
    skip_count = 0
    for item in iter_all_sources():
        sha = item_sha(item)
        seen_sha.add(sha)
        existing = conn.execute(
            "SELECT id, body_embedded FROM knowledge_items WHERE sha = ?", (sha,)
        ).fetchone()
        if existing and (existing["body_embedded"] == int(args.embed_body)):
            skip_count += 1
            continue
        emb = embed_one(item_to_text(item, args.embed_body))
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
                int(args.embed_body),
                emb,
                item.get("updated_at", ""),
                sha,
            ),
        )
        new_count += 1
    # Remove stale items (in db but not seen this pass)
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
    set_meta(
        conn,
        "total_items",
        str(conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]),
    )
    conn.commit()
    conn.close()
    print(
        f"kaizen-knowledge: indexed {new_count} new, "
        f"skipped {skip_count} unchanged, removed {len(stale)} stale",
        file=sys.stderr,
    )


def cmd_reindex(args):
    if DB_PATH.exists():
        DB_PATH.unlink()
    cmd_index(args)


# ─── Search command ──────────────────────────────────────────────────


def cmd_search(args):
    conn = open_db(create=False)
    model, np = _load_model()
    qvec = model.encode(args.query, convert_to_numpy=True, show_progress_bar=False)
    qvec = qvec.astype(np.float32)
    qnorm = qvec / (np.linalg.norm(qvec) + 1e-12)

    where = []
    params: list = []
    if args.source:
        where.append("source = ?")
        params.append(args.source)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM knowledge_items{where_sql}", params
    ).fetchall()

    scored = []
    for r in rows:
        if not r["embedding"]:
            continue
        evec = np.frombuffer(r["embedding"], dtype=np.float32)
        if evec.shape[0] != DEFAULT_DIM:
            continue
        score = float(np.dot(qnorm, evec / (np.linalg.norm(evec) + 1e-12)))
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: args.top_k]

    if args.json:
        out = []
        for score, r in top:
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
        print(json.dumps(out, indent=2))
    else:
        for score, r in top:
            tags = json.loads(r["tags"] or "[]")
            tag_str = f" [{','.join(tags)}]" if tags else ""
            print(
                f"  {score:.3f}  {r['source']:<10} {r['title']}{tag_str}"
            )
            print(f"           → {r['source_path']}")
            if r["snippet"]:
                print(f"           {r['snippet'][:120]}")
    conn.close()


# ─── Other subcommands ───────────────────────────────────────────────


def cmd_stats(args):
    if not DB_PATH.is_file():
        print("kaizen-knowledge: no index yet — run `index` first")
        return
    conn = open_db(create=False)
    print(f"db:        {DB_PATH}")
    print(f"model:     {get_meta(conn, 'model', '?')}")
    print(f"dim:       {get_meta(conn, 'dim', '?')}")
    print(f"indexed:   {get_meta(conn, 'last_indexed_ts', '?')}")
    total = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
    print(f"total:     {total}")
    rows = conn.execute(
        "SELECT source, COUNT(*) AS n FROM knowledge_items GROUP BY source ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        print(f"  {r['source']:<12} {r['n']}")
    conn.close()


def cmd_get(args):
    conn = open_db(create=False)
    r = conn.execute(
        "SELECT * FROM knowledge_items WHERE id = ?", (args.id,)
    ).fetchone()
    if not r:
        sys.exit(f"id {args.id} not found")
    out = {k: r[k] for k in r.keys() if k != "embedding"}
    out["tags"] = json.loads(out.get("tags") or "[]")
    print(json.dumps(out, indent=2))
    conn.close()


def cmd_path(args):
    print(DB_PATH)


def cmd_clear(args):
    if DB_PATH.is_file():
        DB_PATH.unlink()
        print(f"kaizen-knowledge: cleared {DB_PATH}", file=sys.stderr)
    else:
        print("kaizen-knowledge: no index to clear", file=sys.stderr)


# ─── CLI ─────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-knowledge-index",
        description="Semantic search over brain notes, plans, backlog, schemas, persona.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="incremental index of all sources")
    pi.add_argument(
        "--embed-body",
        action="store_true",
        help="also embed snippet body (privacy: defaults to signature only)",
    )
    pi.set_defaults(func=cmd_index)

    pr = sub.add_parser("reindex", help="wipe + full reindex")
    pr.add_argument("--embed-body", action="store_true")
    pr.set_defaults(func=cmd_reindex)

    ps = sub.add_parser("search", help="semantic search")
    ps.add_argument("query")
    ps.add_argument("--top-k", type=int, default=10)
    ps.add_argument(
        "--source",
        choices=["brain-note", "plan", "backlog", "schema", "persona"],
        help="filter results by source type",
    )
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_search)

    pt = sub.add_parser("stats")
    pt.set_defaults(func=cmd_stats)

    pg = sub.add_parser("get")
    pg.add_argument("id", type=int)
    pg.set_defaults(func=cmd_get)

    pp = sub.add_parser("path")
    pp.set_defaults(func=cmd_path)

    pc = sub.add_parser("clear")
    pc.set_defaults(func=cmd_clear)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
