#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "tree-sitter>=0.23",
#   "tree-sitter-rust>=0.23",
#   "tree-sitter-python>=0.23",
# ]
# ///
"""kaizen-tokens CLI — index / ls / show / get.

T4 — thin argparse wrapper over `_token_db.TokenDB` + `_token_extractor`.
Reads from / writes to `<project_root>/.kaizen/token-map.db` (V3
discovery: `KAIZEN_PROJECT_ROOT_OVERRIDE` env first, else CWD-walk to a
`.git` sentinel).

PEP-723 inline-deps mirror the helpers so `uv run --script tokens.py`
spins up a venv with tree-sitter pre-warmed; consumers calling via
`python3 tokens.py` get the same import-time failure tree-sitter would
raise on any extraction path, but the system-stdlib `ls` / `show` /
`get` verbs (which do NOT touch the extractor) keep working.

Verbs
-----
  index               walk the project root, slot every extractable file
  ls                  list indexed files
  ls --file <id>      list slots inside a file (with --json for raw)
  ls --json           dump file directory as JSON
  show <fid> <slot>   stream slot body to stdout (inline or read-by-offset)
  get  <fid> <slot>   print envelope (kind / name / parent / hash / body)
  get  <fid> <slot> --json  same envelope as JSON

Spec: docs/2026-05-18-positional-token-schema-design.md (V3 / V8 / V19).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Sibling imports — _token_db.py + _token_extractor.py live alongside.
sys.path.insert(0, str(Path(__file__).resolve().parent))
# MIGRATION BRIDGE — cross-cluster sibs still at legacy or shimmed there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401, E402 -- adds scripts/<cluster>/ to sys.path
from _token_db import TokenDB  # noqa: E402
from _token_extractor import (  # noqa: E402
    detect_language,
    extract_slots,
    is_extractable,
    normalize_lf,
)

# V19 — skip files larger than 1 MB at index time (tree-sitter parse cost
# and the eventual MCP envelope size make slotting impractical above this).
_MAX_FILE_BYTES = 1_000_000

# Phase 1 — sha256[:32] stands in for blake3; matches _token_extractor.
_GRAMMAR_VERSION = "0.23.0"

# ─── V3 — project-root + DB-path discovery ──────────────────────────

def _project_root() -> Path:
    """Resolve the repo root.

    1. `KAIZEN_PROJECT_ROOT_OVERRIDE` env — wins (test-sandbox hook).
    2. CWD-walk upward until a `.git` directory is found.
    3. Fallback: current working directory.
    """
    override = os.environ.get("KAIZEN_PROJECT_ROOT_OVERRIDE")
    if override:
        return Path(override)
    cur = Path.cwd().resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return Path.cwd()

def _db_path() -> Path:
    return _project_root() / ".kaizen" / "token-map.db"

def _open_db() -> TokenDB:
    db = TokenDB(_db_path())
    db.init_schema()
    return db

def _hash_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]

# ─── index ──────────────────────────────────────────────────────────

def cmd_index(args: argparse.Namespace) -> int:
    """Walk the project root and slot every extractable file."""
    root = _project_root()
    db = _open_db()
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if not is_extractable(rel):
            continue
        try:
            body = path.read_bytes()
        except OSError:
            continue
        if len(body) > _MAX_FILE_BYTES:  # V19
            continue
        lang = detect_language(rel)
        slots = extract_slots(rel, body, lang)
        file_hash = _hash_hex(normalize_lf(body))
        fid = db.upsert_file(
            path=str(rel),
            blake3=file_hash,
            language=lang,
            grammar_version=_GRAMMAR_VERSION,
            mtime=int(path.stat().st_mtime),
        )
        db.upsert_slots(fid, slots)
        count += 1
        if count % 100 == 0:
            print(f"  indexed {count} files...", file=sys.stderr)
    print(f"kaizen-tokens: indexed {count} file(s)")
    return 0

# ─── ls ─────────────────────────────────────────────────────────────

def cmd_ls(args: argparse.Namespace) -> int:
    """List files (default) or slots inside a specific file."""
    db = _open_db()
    if args.file is not None:
        rows = db.conn.execute(
            "SELECT slot, kind, name, parent_qualifier, tombstoned "
            "FROM slots WHERE file_id=? ORDER BY slot",
            (args.file,),
        ).fetchall()
        if args.json:
            print(json.dumps([dict(r) for r in rows], indent=2))
        else:
            for r in rows:
                tag = " (tombstoned)" if r["tombstoned"] else ""
                pn = (
                    f"{r['parent_qualifier']}::"
                    if r["parent_qualifier"] else ""
                )
                print(
                    f"  [{r['slot']:3d}] {r['kind']:8s} "
                    f"{pn}{r['name'] or ''}{tag}"
                )
    else:
        rows = db.conn.execute(
            "SELECT file_id, path, language, version FROM files "
            "WHERE path_gone=0 ORDER BY file_id"
        ).fetchall()
        if args.json:
            print(json.dumps([dict(r) for r in rows], indent=2))
        else:
            for r in rows:
                lang = r["language"] or "?"
                print(
                    f"  {r['file_id']:4d}  {lang:8s}  "
                    f"v{r['version']:3d}  {r['path']}"
                )
    return 0

# ─── show ───────────────────────────────────────────────────────────

def cmd_show(args: argparse.Namespace) -> int:
    """Stream a slot's body to stdout. V8 — inline if cached, else offsets."""
    db = _open_db()
    row = db.get_slot(args.file_id, args.slot)
    if row is None:
        print(
            f"kaizen-tokens: no slot {args.slot} for file {args.file_id}",
            file=sys.stderr,
        )
        return 1
    body = row["body"]
    if body is None:
        path_row = db.conn.execute(
            "SELECT path FROM files WHERE file_id=?", (args.file_id,),
        ).fetchone()
        if path_row is None:
            print(
                f"kaizen-tokens: file_id {args.file_id} not found",
                file=sys.stderr,
            )
            return 1
        full = (_project_root() / path_row["path"]).read_bytes()
        body = full[row["byte_start"]:row["byte_end"]]
    sys.stdout.buffer.write(body)
    if not body.endswith(b"\n"):
        sys.stdout.buffer.write(b"\n")
    return 0

# ─── get ────────────────────────────────────────────────────────────

def cmd_get(args: argparse.Namespace) -> int:
    """Print the full envelope for a slot (CLI peer of MCP read_token)."""
    db = _open_db()
    row = db.get_slot(args.file_id, args.slot)
    if row is None:
        print(
            f"kaizen-tokens: no slot {args.slot} for file {args.file_id}",
            file=sys.stderr,
        )
        return 1
    path_row = db.conn.execute(
        "SELECT path, version FROM files WHERE file_id=?",
        (args.file_id,),
    ).fetchone()
    if path_row is None:
        print(
            f"kaizen-tokens: file_id {args.file_id} not found",
            file=sys.stderr,
        )
        return 1
    body = row["body"]
    if body is None:
        full = (_project_root() / path_row["path"]).read_bytes()
        body = full[row["byte_start"]:row["byte_end"]]
    envelope = {
        "file_id":      args.file_id,
        "slot":         args.slot,
        "kind":         row["kind"],
        "name":         row["name"],
        "parent":       row["parent_qualifier"],
        "path":         path_row["path"],
        "version":      path_row["version"],
        "content_hash": row["content_hash"],
        "tombstoned":   bool(row["tombstoned"]),
        "body":         body.decode("utf-8", errors="replace"),
    }
    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        for k, v in envelope.items():
            if k == "body":
                continue
            print(f"  {k}: {v}")
        print("  body:")
        print(envelope["body"])
    return 0

# ─── argparse wiring ────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kaizen-tokens",
        description="Positional token map CLI (index / ls / show / get).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("index", help="walk repo root and slot every file").set_defaults(
        func=cmd_index
    )

    ls = sub.add_parser("ls", help="list files (or slots with --file)")
    ls.add_argument("--file", type=int, help="file_id to inspect")
    ls.add_argument("--json", action="store_true", help="emit JSON")
    ls.set_defaults(func=cmd_ls)

    sh = sub.add_parser("show", help="stream a slot's body to stdout")
    sh.add_argument("file_id", type=int)
    sh.add_argument("slot", type=int)
    sh.set_defaults(func=cmd_show)

    gt = sub.add_parser("get", help="print envelope for a slot")
    gt.add_argument("file_id", type=int)
    gt.add_argument("slot", type=int)
    gt.add_argument("--json", action="store_true", help="emit JSON")
    gt.set_defaults(func=cmd_get)

    return p

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
