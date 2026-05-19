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
"""kaizen trace-index — SQLite-backed semantic search over trace events.

**CPU-only torch** by default. PEP 723 above pins `torch` to the CPU
wheel index (`pytorch-cpu`), saving ~3.5 GB of CUDA libraries from the
uv-managed venv. For GPU inference, invoke `trace_index_gpu.py` instead
(see `bin/kaizen-trace-index` — env var `KAIZEN_TRACE_GPU=1` switches).

Indexes `~/.claude/.kaizen-trace/events.jsonl` (+ rotated `.gz`) into
`~/.claude/.kaizen-trace/index.db`. Each event gets a 384-dim embedding
from `sentence-transformers` (default model: `all-MiniLM-L6-v2`).

## Privacy

By default, ONLY the event signature is embedded — `src + evt + tool +
sid_prefix`. NO payload data (commands, file paths, prompts). This keeps
the embeddings privacy-safe and predictable.

Opt-in via `--embed-data` to also embed selected `data` fields (model
name, status code, ms). Sensitive fields (auth, secrets, full prompts)
are NEVER embedded regardless of flag.

## SQLite schema

    trace_events:
        id          INTEGER PRIMARY KEY
        ts          TEXT NOT NULL      -- ISO UTC
        src         TEXT NOT NULL
        evt         TEXT NOT NULL
        sid         TEXT
        tool        TEXT
        ms          INTEGER
        data_json   TEXT               -- raw event data field (json.dumps)
        embedding   BLOB               -- np.float32 array, dim=384

    trace_meta:
        key         TEXT PRIMARY KEY
        value       TEXT

        Keys: model, dim, last_indexed_ts, total_events, version

## Subcommands

    index [--max N] [--embed-data]    incremental index of new events
    reindex                            wipe + full reindex
    search "<query>" [--top-k 10]      semantic search
                       [--src S] [--sid SID] [--since 1h] [--json]
    stats                              total indexed, model, latest ts
    get <id>                           fetch one event by id
    path                               print db path
    clear                              drop the index (next index re-creates)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

HOME = Path(os.path.expanduser("~"))

# v1.22.0+: paths come from the shared _paths module (config.py is the SSOT).
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
# MIGRATION BRIDGE — until helpers move from skills/workflow/scripts/ → scripts/
sys.path.insert(0, str(_SCRIPT_DIR.parents[1] / "skills" / "workflow" / "scripts"))
import _paths as _p  # noqa: E402
import config as _cfg  # noqa: E402

TRACE_FILE = _p.TRACE_FILE
TRACE_DIR = _p.TRACE_DIR
DB_PATH = _p.TRACE_DB

DEFAULT_MODEL = os.environ.get("KAIZEN_TRACE_EMBED_MODEL", _cfg.EMBED_MODEL)
DEFAULT_DIM = _cfg.EMBED_DIM

# Lazy imports — only load model when needed
_model = None
_np = None


def _load_model():
    """Import sentence-transformers + numpy on demand. Heavy (~500MB w/ torch);
    cached after first call."""
    global _model, _np
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as e:
            sys.stderr.write(
                f"kaizen-trace-index: missing dep: {e}\n"
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
    CREATE TABLE IF NOT EXISTS trace_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        src TEXT NOT NULL,
        evt TEXT NOT NULL,
        sid TEXT,
        tool TEXT,
        ms INTEGER,
        data_json TEXT,
        embedding BLOB,
        content_hash TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_ts ON trace_events(ts);
    CREATE INDEX IF NOT EXISTS idx_src ON trace_events(src);
    CREATE INDEX IF NOT EXISTS idx_sid ON trace_events(sid);
    CREATE INDEX IF NOT EXISTS idx_evt ON trace_events(evt);
    CREATE TABLE IF NOT EXISTS trace_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
"""


def open_db(create: bool = True) -> sqlite3.Connection:
    return _kz_sqlite.open_indexer_db(DB_PATH, _SCHEMA_SQL, create=create)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    _kz_sqlite.set_meta(conn, "trace_meta", key, value)


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    return _kz_sqlite.get_meta(conn, "trace_meta", key, default)


# ─── Embedding ───────────────────────────────────────────────────────


def event_to_text(ev: dict, embed_data: bool = False) -> str:
    """Build the embeddable text from an event. Privacy-safe by default:
    src + evt + tool + first-8 of sid. With --embed-data: + model + status."""
    bits = [
        f"source: {ev.get('src', '')}",
        f"event: {ev.get('evt', '')}",
    ]
    if ev.get("tool"):
        bits.append(f"tool: {ev['tool']}")
    sid = ev.get("sid", "")
    if sid:
        bits.append(f"session: {sid[:8]}")
    if ev.get("ms") is not None:
        # Categorize latency for semantic anchoring
        ms = ev["ms"]
        if ms < 100:
            bits.append("latency: fast")
        elif ms < 1000:
            bits.append("latency: normal")
        elif ms < 5000:
            bits.append("latency: slow")
        else:
            bits.append("latency: very slow")

    if embed_data and ev.get("data"):
        data = ev["data"]
        # SAFE fields only — never embed full payload
        for safe_key in ("model", "status", "verdict", "outcome", "kind"):
            if safe_key in data:
                bits.append(f"{safe_key}: {data[safe_key]}")

    return " | ".join(bits)


def content_hash(ev: dict) -> str:
    """Stable identity hash for de-dup. Based on ts + src + evt + sid + tool."""
    s = f"{ev.get('ts','')}|{ev.get('src','')}|{ev.get('evt','')}|{ev.get('sid','')}|{ev.get('tool','')}|{ev.get('ms','')}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# ─── Index command ───────────────────────────────────────────────────


from _jsonl import iter_jsonl  # noqa: E402 — shared helper (M4 dedup)


def iter_all_events():
    files = []
    if TRACE_DIR.exists():
        files = sorted(TRACE_DIR.glob("events-*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    if TRACE_FILE.exists():
        files.append(TRACE_FILE)
    for f in files:
        yield from iter_jsonl(f)


import _embed as _kz_embed  # v1.25.0+: HTTP-first embedding backend
from _progress import Progress as _Progress  # v1.30.0+: live stderr progress


def cmd_index(max_n: Optional[int] = None, embed_data: bool = False) -> dict:
    """Incremental index: skip events whose content_hash is already in db."""
    conn = open_db()

    # v1.25.0+: resolve the actual backend; model/dim come from there.
    backend = _kz_embed.resolve_backend()
    active_model = backend.get("model", DEFAULT_MODEL)

    # Set/check model + dim
    stored_model = get_meta(conn, "model", "")
    if stored_model and stored_model != active_model:
        print(f"  ! model changed ({stored_model} → {active_model}); reindex recommended", file=sys.stderr)
    set_meta(conn, "model", active_model)
    set_meta(conn, "backend_kind", backend.get("kind", "local"))

    # Existing hashes
    existing = set(row["content_hash"] for row in conn.execute("SELECT content_hash FROM trace_events"))

    # Collect new events
    sys.stderr.write("[trace] scanning event log…\n"); sys.stderr.flush()
    new_events = []
    for ev in iter_all_events():
        h = content_hash(ev)
        if h in existing:
            continue
        new_events.append((ev, h))
        if max_n and len(new_events) >= max_n:
            break

    if not new_events:
        sys.stderr.write(f"[trace] no new events (total in db: {len(existing)})\n"); sys.stderr.flush()
        return {"indexed": 0, "total": len(existing), "model": active_model}

    # Batch embed via _embed (HTTP /v1/embeddings or local sentence-transformers).
    sys.stderr.write(f"[trace] embedding {len(new_events)} new events via {active_model}…\n"); sys.stderr.flush()
    texts = [event_to_text(ev, embed_data=embed_data) for ev, _ in new_events]
    embeddings_bytes, actual_dim = _kz_embed.embed_batch(texts)
    set_meta(conn, "dim", str(actual_dim))

    # Insert — embeddings_bytes is already a list of float32 bytes from _kz_embed.embed_batch.
    bar = _Progress("trace", total=len(new_events))
    for (ev, h), emb_blob in zip(new_events, embeddings_bytes):
        data_json = json.dumps(ev.get("data", {}), separators=(",", ":")) if ev.get("data") else None
        conn.execute("""
            INSERT OR IGNORE INTO trace_events
            (ts, src, evt, sid, tool, ms, data_json, embedding, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ev.get("ts", ""),
            ev.get("src", ""),
            ev.get("evt", ""),
            ev.get("sid", ""),
            ev.get("tool", ""),
            ev.get("ms"),
            data_json,
            emb_blob,
            h,
        ))
        bar.tick(f"{ev.get('src', '?')}/{ev.get('evt', '?')}")
    bar.done(f"{len(new_events)} indexed")

    set_meta(conn, "last_indexed_ts", _now_iso())
    total = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
    set_meta(conn, "total_events", str(total))
    conn.commit()
    conn.close()

    return {"indexed": len(new_events), "total": total, "model": DEFAULT_MODEL}


def cmd_reindex(embed_data: bool = False) -> dict:
    """Drop the table + rebuild from scratch."""
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("DROP TABLE IF EXISTS trace_events")
        conn.execute("DROP TABLE IF EXISTS trace_meta")
        conn.commit()
        conn.close()
    return cmd_index(embed_data=embed_data)


# ─── Search command ──────────────────────────────────────────────────


def parse_since(s: str) -> Optional[dt.datetime]:
    m = re.fullmatch(r"(\d+)([smhd])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=n * mult)
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def cmd_search(query: str, top_k: int = 10, src: str = "", sid: str = "",
                evt: str = "", since: Optional[str] = None) -> list[dict]:
    """Semantic search. Cosine-similarity against all stored embeddings,
    filtered by optional fields, top-K returned.

    M6: scoring/embed/dim-filter loop lives in `_search.cosine_topk`.
    SQL pre-filters (src/sid/evt/since) are plumbed through `where`."""
    if not DB_PATH.exists():
        sys.stderr.write("trace-search: index not built. Run: kaizen-trace-index index\n")
        return []
    import _search as _kz_search

    conn = open_db(create=False)

    # SQL filters
    where_clauses: list[str] = []
    params: list = []
    if src:
        where_clauses.append("src = ?")
        params.append(src)
    if sid:
        where_clauses.append("sid = ?")
        params.append(sid)
    if evt:
        where_clauses.append("evt = ?")
        params.append(evt)
    if since:
        since_dt = parse_since(since)
        if since_dt is not None:
            where_clauses.append("ts >= ?")
            params.append(since_dt.isoformat(timespec="milliseconds").replace("+00:00", "Z"))

    scored = _kz_search.cosine_topk(
        conn, "trace_events", query,
        top_k=top_k,
        select_cols="id, ts, src, evt, sid, tool, ms, data_json, embedding",
        where=" AND ".join(where_clauses),
        params=params,
    )

    out = []
    for row, sim in scored:
        data = json.loads(row["data_json"]) if row["data_json"] else {}
        out.append({
            "id": row["id"],
            "score": round(sim, 4),
            "ts": row["ts"],
            "src": row["src"],
            "evt": row["evt"],
            "sid": row["sid"] or "",
            "tool": row["tool"] or "",
            "ms": row["ms"],
            "data": data,
        })
    conn.close()
    return out


# ─── Misc ────────────────────────────────────────────────────────────


from _time import iso  # M5 dedup


def _now_iso() -> str:
    return iso()


def cmd_stats() -> dict:
    if not DB_PATH.exists():
        return {"db": str(DB_PATH), "exists": False}
    conn = open_db(create=False)
    total = conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
    by_src = dict(conn.execute("SELECT src, COUNT(*) FROM trace_events GROUP BY src ORDER BY COUNT(*) DESC").fetchall())
    latest = conn.execute("SELECT ts FROM trace_events ORDER BY ts DESC LIMIT 1").fetchone()
    earliest = conn.execute("SELECT ts FROM trace_events ORDER BY ts LIMIT 1").fetchone()
    out = {
        "db": str(DB_PATH),
        "exists": True,
        "total": total,
        "by_src": by_src,
        "earliest_ts": earliest["ts"] if earliest else None,
        "latest_ts": latest["ts"] if latest else None,
        "model": get_meta(conn, "model"),
        "dim": get_meta(conn, "dim"),
        "last_indexed_ts": get_meta(conn, "last_indexed_ts"),
    }
    conn.close()
    return out


def cmd_get(event_id: int) -> Optional[dict]:
    if not DB_PATH.exists():
        return None
    conn = open_db(create=False)
    row = conn.execute(
        "SELECT id, ts, src, evt, sid, tool, ms, data_json FROM trace_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "ts": row["ts"],
        "src": row["src"],
        "evt": row["evt"],
        "sid": row["sid"] or "",
        "tool": row["tool"] or "",
        "ms": row["ms"],
        "data": json.loads(row["data_json"]) if row["data_json"] else {},
    }


def cmd_clear() -> str:
    if DB_PATH.exists():
        DB_PATH.unlink()
        return f"removed {DB_PATH}"
    return "(no index to clear)"


# ─── CLI (M7: thin IndexerCLI subclass) ──────────────────────────────


from _indexer_cli import IndexerCLI  # noqa: E402
import _envelope  # noqa: E402

_emit = _envelope.emitter("kaizen-trace-search", tool_version="1.0.0")


class TraceCLI(IndexerCLI):
    PROG = "trace_index.py"
    DESCRIPTION = __doc__
    DB_PATH = DB_PATH
    SUBCOMMAND_REQUIRED = False  # bare invocation defaults to `index`

    def do_stats(self, args):
        return cmd_stats()

    def do_get(self, args):
        return cmd_get(args.id)

    def do_search(self, args):
        return cmd_search(
            args.query, top_k=args.top_k, src=args.src,
            sid=args.sid, evt=args.evt, since=args.since,
        )

    def do_index(self, args):
        return cmd_index(
            max_n=getattr(args, "max", None),
            embed_data=getattr(args, "embed_data", False),
        )

    def do_reindex(self, args):
        return cmd_reindex(embed_data=args.embed_data)

    def do_clear(self, args):
        return {"message": cmd_clear()}

    def extra_index_args(self, p):
        p.add_argument("--max", type=int, default=None,
                       help="cap new-event count this run")
        p.add_argument("--embed-data", action="store_true",
                       help="also embed safe data fields (model, status, verdict)")

    def extra_reindex_args(self, p):
        p.add_argument("--embed-data", action="store_true")

    def extra_search_args(self, p):
        p.add_argument("--src", default="")
        p.add_argument("--sid", default="")
        p.add_argument("--evt", default="")
        p.add_argument("--since", default=None)

    def cmd_search(self, args):
        """Override base to wrap --json output in canonical envelope."""
        results = self.do_search(args)
        if getattr(args, "json", False):
            _emit({"query": args.query, "results": results},
                  counts={"results": len(results)})
            return
        self.print_search(results, args)

    def print_search(self, results, args):
        for r in results:
            ts = r["ts"][:23]
            print(
                f"  [{r['score']:.3f}] {ts}  {r['src']:6}  {r['evt']:25}  "
                f"tool={r['tool'] or '-':8}  "
                f"ms={r['ms'] if r['ms'] is not None else '-'}"
            )
        print(f"\n--- {len(results)} hits", file=sys.stderr)

    def print_get(self, rec, args):
        print(
            json.dumps(rec, indent=2, default=str) if rec else "(not found)"
        )

    def print_clear(self, result, args):
        print(result.get("message", ""))


def main():
    cli = TraceCLI()
    parser = cli.build_parser()
    argv = sys.argv[1:]
    args = parser.parse_args(argv)
    # Bare invocation → default to `index` (preserves old behavior).
    if args.cmd is None:
        args = parser.parse_args(["index"])
    args.func(args)


if __name__ == "__main__":
    main()
