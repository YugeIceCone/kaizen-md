"""kaizen _atomic — shared atomic write helper.

Single source for the tempfile+rename pattern used across handoff
auto-finalize / create, dxm session links, scaffold YAML writes, and
any future writer that needs "all-or-nothing" file mutation.

## Why a shared util

Each consumer was reimplementing `path.with_suffix(".tmp").write_text +
.replace(path)` inline. Subtle bugs differed:
- Some forgot parent dir creation
- Some used `.tmp` extension that collided with editor swap files
- Some forgot the cross-platform `os.replace` (vs `os.rename` which is
  not atomic on Windows over existing files)
- A few used context-less `open(..., "w")` which truncates the target
  before fsync — defeating atomicity on power loss

## API

    atomic_write(path, content, *, encoding="utf-8")
        Write a string atomically. Creates parent dirs.

    atomic_write_json(path, data, *, indent=2, sort_keys=True)
        Same but for JSON-encodable dict/list. Determinism on by default.

    atomic_append_line(path, line)
        Append one line + newline to a file. Append-only files (JSONL
        event streams) get this primitive because tempfile+rename
        loses prior content.

## Atomicity guarantees

- POSIX: `os.replace` is atomic when src + dst are on the same filesystem.
  The tempfile is created in the SAME DIRECTORY as the target to
  guarantee this (cross-filesystem rename falls back to copy+unlink).
- Windows: `os.replace` is atomic since Python 3.3 (uses MoveFileEx
  under the hood with replace-existing semantics).
- atomic_append_line is NOT replace-based — it relies on Linux's
  atomic append for writes < PIPE_BUF (4096 bytes). For larger
  records, use atomic_write to a versioned filename instead.

Stdlib only. No deps.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

def _ensure_parent(path: Path) -> None:
    parent = path.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

def atomic_write(path: os.PathLike | str, content: str,
                  *, encoding: str = "utf-8") -> None:
    """Write `content` to `path` atomically. Creates parent dirs.

    Uses tempfile-in-same-dir + os.replace. On error during write,
    the tempfile is cleaned up and the target is untouched.
    """
    target = Path(path)
    _ensure_parent(target)
    # NamedTemporaryFile with delete=False so we control the rename
    # path. dir=parent guarantees same-filesystem for atomic rename.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".part",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_name, target)
    except BaseException:
        # Clean up the tempfile on any exception (including KeyboardInterrupt)
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

def atomic_write_bytes(path: os.PathLike | str, content: bytes) -> None:
    """Write `content` (bytes) to `path` atomically. Creates parent dirs.

    Symmetric to atomic_write but for binary content (blobs, sidecars).
    """
    target = Path(path)
    _ensure_parent(target)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".part",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

def atomic_write_json(path: os.PathLike | str, data: Any,
                       *, indent: int = 2, sort_keys: bool = True) -> None:
    """Write `data` as JSON to `path` atomically.

    sort_keys=True by default for determinism — two runs producing
    the same logical data produce byte-identical output.
    """
    body = json.dumps(data, indent=indent, sort_keys=sort_keys,
                       default=str) + "\n"
    atomic_write(path, body)

def atomic_append_line(path: os.PathLike | str, line: str) -> None:
    """Append one line + newline to `path`. Creates parent dirs.

    Designed for JSONL event streams. Relies on Linux's atomic-append
    semantics for writes < PIPE_BUF (4096 bytes). For larger records,
    consider atomic_write to a versioned filename.

    The supplied line is written verbatim with a trailing newline. If
    `line` already ends with '\\n', no double-newline.
    """
    target = Path(path)
    _ensure_parent(target)
    suffix = "" if line.endswith("\n") else "\n"
    with target.open("a", encoding="utf-8") as f:
        f.write(line + suffix)

__all__ = ["atomic_write", "atomic_write_json", "atomic_append_line"]
