#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "tree-sitter>=0.23",
#   "tree-sitter-rust>=0.23",
#   "tree-sitter-python>=0.23",
# ]
# ///
"""Watcher integration — file event → token-map DB update.

T6 — single entry point `process_file_event(db, root, rel_path, event)`
called by the kaizen-watch daemon for every file-system event. The
function honors all V-flags from spec
`docs/2026-05-18-positional-token-schema-design.md`:

  V1   rename detection — handled inside `TokenDB.upsert_file`; this
       function only fires `mark_path_gone` on delete events so the
       next-tick `upsert_file` can rebind the file_id.
  V19  size cap — files > 1 MB are skipped (no extract, no upsert).
  V21/V22  exclusion list — paths under target/, node_modules/, .venv/
       etc. are silently dropped via `is_extractable`.
  V23  CRLF normalization — `normalize_lf` runs before sha256 so the
       blake3 column stays stable across Windows checkouts.
  V25  IMMEDIATE-tx — `upsert_slots` already wraps each batch in
       `with self.conn:`; this function does NOT need its own tx.

The PEP-723 header mirrors `_token_extractor.py` so the script can run
under `uv run --script` with all 3 grammars pre-installed; tests use
`__main__ --test` to drive a single event through the uv venv where
tree-sitter is reachable.

Private helper (underscore-prefixed) — exempt from `bin-wrapper-per-cli`
iron-law. Consumed in-process by the watcher daemon (T7 wires it up).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# Allow `from _token_db import ...` whether imported as a sibling module
# or invoked directly via `uv run --script`.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _token_db import TokenDB  # noqa: E402
from _token_extractor import (  # noqa: E402
    detect_language,
    extract_slots,
    is_extractable,
    normalize_lf,
)

__all__ = ["process_file_event"]

_SIZE_CAP_BYTES = 1_000_000  # V19
_GRAMMAR_VERSION = "0.23.0"  # mirrors PEP-723 dep pin

def process_file_event(
    db: TokenDB, root: Path, rel_path: Path, event: str,
) -> None:
    """Handle a single watcher event. `event` ∈ {"modified", "deleted"}.

    Flow:
      1. Exclusion gate (V21/V22) — early return for build outputs.
      2. Delete (or missing-on-disk) → `mark_path_gone` so the next
         upsert can match by blake3 (V1 rename detection).
      3. Read body, enforce V19 size cap, V23 LF-normalize for hash.
      4. Upsert file row (V1/V20 rename + grammar-version), extract
         fresh slot list, diff against live slots, tombstone removed
         slots, then upsert the new set (V25 IMMEDIATE-tx inside
         `upsert_slots`).
    """
    if not is_extractable(rel_path):
        return

    abs_path = root / rel_path

    if event == "deleted" or not abs_path.exists():
        db.mark_path_gone(str(rel_path))
        return

    try:
        body = abs_path.read_bytes()
    except OSError:
        # Race: file vanished between event dispatch and read. Treat as
        # delete so the DB stays consistent with disk.
        db.mark_path_gone(str(rel_path))
        return

    if len(body) > _SIZE_CAP_BYTES:
        return  # V19 — oversized blob, skip entirely

    lang = detect_language(rel_path)
    body_hash = hashlib.sha256(normalize_lf(body)).hexdigest()[:32]

    fid = db.upsert_file(
        path=str(rel_path),
        blake3=body_hash,
        language=lang,
        grammar_version=_GRAMMAR_VERSION,
        mtime=int(abs_path.stat().st_mtime),
    )

    new_slots = extract_slots(rel_path, body, lang)
    new_slot_ids = {s.slot for s in new_slots}

    # Diff: any live slot not present in the fresh parse → tombstone.
    existing = db.conn.execute(
        "SELECT slot FROM slots WHERE file_id=? AND tombstoned=0", (fid,),
    ).fetchall()
    for row in existing:
        if row["slot"] not in new_slot_ids:
            db.tombstone_slot(fid, row["slot"])

    db.upsert_slots(fid, new_slots)

# ─── __main__ — JSON-driven test entry point (uv-venv path) ──────────

def _main_test() -> int:
    """Drive a single `process_file_event` call from a JSON payload on
    stdin. Used by tests/test_token_watch.py to exercise the tree-sitter
    parse path under the script's PEP-723 uv venv (system python doesn't
    see tree-sitter; this script does via `uv run --script`).

    Payload shape: {"db_path": str, "root": str, "rel_path": str, "event": str}
    """
    import json

    payload = json.loads(sys.stdin.read())
    db = TokenDB(Path(payload["db_path"]))
    db.init_schema()
    process_file_event(
        db,
        Path(payload["root"]),
        Path(payload["rel_path"]),
        event=payload["event"],
    )
    db.conn.close()
    return 0

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        raise SystemExit(_main_test())
    # Default probe — confirm uv venv has the 3 deps (mirrors siblings).
    import tree_sitter        # noqa: F401
    import tree_sitter_rust   # noqa: F401
    import tree_sitter_python # noqa: F401
    print("_token_watch.py: deps OK")
