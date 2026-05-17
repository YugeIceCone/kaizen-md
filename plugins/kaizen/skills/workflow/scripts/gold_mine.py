#!/usr/bin/env python3
"""kaizen-gold-mine — auto-miner: scan dxm + trace event streams, mine
signal-bearing events into gold proposals.

MVP slice (phased):

    Phase 1  cursor + mtime short-circuit + tail-diff (this file, stdlib)
    Phase 2  mechanical filter + normalize + dedup + anti-recursion
    Phase 3  optional Ollama scoring (KAIZEN_GOLD_MINE_ENABLE=1)
    Phase 4  threshold gate + proposals.jsonl + review CLI (in gold.py)
    Phase 5  SessionEnd hook wiring

## Cursor

    $KAIZEN_DIR/gold/<project-slug>/mine-cursor.json
    {
      "dxm":   {"inode": N, "byte_offset": N, "sha256_tail_4kb": "...",
                 "line_count": N, "mtime": N.N},
      "trace": { ...same shape... }
    }

3-level short-circuit (cheapest → most expensive):
    (1) mtime same as cursor.mtime           → exit, no read
    (2) inode changed                        → rotation; re-scan from 0
    (3) tail-hash matches cursor.tail        → exit (mtime bumped but
                                                content identical, e.g.
                                                touch)
    else                                      → seek(byte_offset), read,
                                                return new lines.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional


_TAIL_BYTES = 4096

# Public contract thresholds — see test_gold_mine_contract.TestThresholdGate.
# score < PROPOSAL_THRESHOLD                → drop
# PROPOSAL_THRESHOLD ≤ score < AUTO_CAPTURE → proposals.jsonl (status=pending)
# score ≥ AUTO_CAPTURE_THRESHOLD            → patterns.jsonl (auto-captured)
PROPOSAL_THRESHOLD = 0.75
AUTO_CAPTURE_THRESHOLD = 0.85


def _kaizen_dir() -> Path:
    env = os.environ.get("KAIZEN_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / ".claude" / ".kaizen"


def _project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".kaizen").is_dir() or (parent / ".git").is_dir():
            return parent
    return cwd


def _project_slug() -> str:
    return str(_project_root().resolve()).replace("/", "-")


def cursor_path() -> Path:
    """Project-scoped cursor location under $KAIZEN_DIR/gold/<slug>/."""
    return _kaizen_dir() / "gold" / _project_slug() / "mine-cursor.json"


def load_cursor() -> dict:
    """Return the cursor dict; {} when missing or unreadable."""
    p = cursor_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cursor(cursor: dict) -> None:
    """Persist the cursor atomically (write tmp → rename)."""
    p = cursor_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cursor, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _tail_sha256(path: Path, size: int) -> str:
    """SHA256 of the last `_TAIL_BYTES` bytes (or whole file if smaller).

    Used as a content-fingerprint to short-circuit when mtime changed but
    file content didn't (e.g. `touch`).
    """
    n = min(_TAIL_BYTES, size)
    if n <= 0:
        return hashlib.sha256(b"").hexdigest()
    with path.open("rb") as f:
        f.seek(size - n)
        chunk = f.read(n)
    return hashlib.sha256(chunk).hexdigest()


def _stat_or_none(path: Path):
    try:
        return path.stat()
    except OSError:
        return None


def read_new_lines(
    target: Path,
    prior: Optional[dict],
) -> tuple[list[str], dict]:
    """Return (new_lines, new_cursor) for `target` given `prior` cursor.

    `prior` is the per-watch-target cursor dict (e.g. `cursor["dxm"]`),
    not the whole cursor file. Caller is responsible for slicing.

    Returns ([], {}) when the target file is missing entirely. Returns
    ([], prior) on any short-circuit.
    """
    st = _stat_or_none(target)
    if st is None:
        return [], {}

    size = st.st_size
    inode = st.st_ino
    mtime = st.st_mtime

    # Level 1: mtime short-circuit (cheapest)
    if prior and prior.get("mtime") == mtime and prior.get("inode") == inode:
        return [], dict(prior)

    # Level 2: inode change → rotation, re-scan from 0
    if prior and prior.get("inode") != inode:
        prior = None  # fall through to full-read path

    # Level 3: tail-hash short-circuit (mtime bumped but content same)
    tail_hash = _tail_sha256(target, size)
    if prior and prior.get("sha256_tail_4kb") == tail_hash \
              and prior.get("byte_offset") == size:
        # Update mtime in the returned cursor so next call's L1 skips early.
        new_cursor = dict(prior)
        new_cursor["mtime"] = mtime
        return [], new_cursor

    # Read from the prior byte_offset (or 0 on first read / rotation).
    start = (prior or {}).get("byte_offset", 0)
    if start > size:
        # File shrunk without inode change (rare; treat as rotation).
        start = 0

    lines: list[str] = []
    try:
        with target.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(start)
            for line in f:
                lines.append(line)
    except OSError:
        return [], dict(prior) if prior else {}

    # Count prior line_count when available (we don't re-count the
    # whole file — only delta).
    prior_lines = (prior or {}).get("line_count", 0) if prior else 0
    new_cursor = {
        "inode":            inode,
        "byte_offset":      size,
        "sha256_tail_4kb":  tail_hash,
        "line_count":       prior_lines + len(lines),
        "mtime":            mtime,
    }
    return lines, new_cursor


__all__ = [
    "cursor_path",
    "load_cursor",
    "save_cursor",
    "read_new_lines",
]
