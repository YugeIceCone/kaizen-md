#!/usr/bin/env python3
"""kaizen cache — hash-keyed JSON cache, per-repo.

Location: `<repo>/.kaizen/cache/` (gitignored under `.kaizen/`).

Each entry is a JSON file `<key>.json`. Keys are SHA1 hashes of input
tuples, truncated to 16 hex chars (~64 bits — plenty for a single-repo
cache that never holds more than a few hundred entries).

**No TTL.** Entries invalidate when inputs change — you compose a new
key from new inputs, so a stale entry becomes unreachable on the next
lookup. Manual `clear` available for hygiene.

## Library usage

    from cache import key_of, get, put
    k = key_of("agent-reviewer", diff_sha1)
    if (cached := get(k)) is not None:
        return cached
    result = expensive_op()
    put(k, result)
    return result

## CLI usage

    cache.py                       → stats (default)
    cache.py key <part1> <part2>…  → print a key derived from parts
    cache.py get <key>             → print cached value (exit 1 if miss)
    cache.py put <key> <json>      → write value
    cache.py clear                 → remove all entries
    cache.py stats                 → count + bytes + dir

## Env

    KAIZEN_CACHE_DIR — override the per-repo cache dir (advanced).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    override = os.environ.get("KAIZEN_CACHE_DIR")
    if override:
        return Path(override).parent.parent if Path(override).name == "cache" else Path(override)
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def cache_dir() -> Path:
    override = os.environ.get("KAIZEN_CACHE_DIR")
    if override:
        return Path(override)
    return _repo_root() / ".kaizen" / "cache"


def _ensure() -> Path:
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def key_of(*parts: object) -> str:
    """Compose a 16-hex-char SHA1 key from input parts.

    Parts are stringified and null-byte-separated to prevent
    ambiguity (e.g. ['ab', 'c'] vs ['a', 'bc']).
    """
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode())
        h.update(b"\x00")
    return h.hexdigest()[:16]


def get(key: str) -> dict | None:
    d = _ensure()
    p = d / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def put(key: str, value: dict) -> None:
    d = _ensure()
    p = d / f"{key}.json"
    p.write_text(json.dumps(value, indent=2, sort_keys=True))


def delete(key: str) -> bool:
    p = cache_dir() / f"{key}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def clear() -> int:
    d = cache_dir()
    if not d.exists():
        return 0
    n = 0
    for p in d.glob("*.json"):
        p.unlink()
        n += 1
    return n


def stats() -> dict:
    d = cache_dir()
    if not d.exists():
        return {"count": 0, "bytes": 0, "dir": str(d), "exists": False}
    files = list(d.glob("*.json"))
    total = sum(f.stat().st_size for f in files)
    return {"count": len(files), "bytes": total, "dir": str(d), "exists": True}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "key":
        if len(sys.argv) < 3:
            sys.exit("usage: cache.py key <part1> [part2] ...")
        print(key_of(*sys.argv[2:]))

    elif cmd == "get":
        if len(sys.argv) < 3:
            sys.exit("usage: cache.py get <key>")
        r = get(sys.argv[2])
        if r is None:
            sys.exit(1)
        print(json.dumps(r))

    elif cmd == "put":
        if len(sys.argv) < 4:
            sys.exit("usage: cache.py put <key> <json>")
        try:
            value = json.loads(sys.argv[3])
        except json.JSONDecodeError as e:
            sys.exit(f"invalid json: {e}")
        put(sys.argv[2], value)

    elif cmd == "delete":
        if len(sys.argv) < 3:
            sys.exit("usage: cache.py delete <key>")
        print("ok" if delete(sys.argv[2]) else "miss")

    elif cmd == "clear":
        print(f"cleared {clear()} entries from {cache_dir()}")

    elif cmd == "stats":
        print(json.dumps(stats(), indent=2))

    elif cmd in ("-h", "--help"):
        print(__doc__)

    else:
        sys.exit(f"unknown subcommand: {cmd}\ntry: key|get|put|delete|clear|stats")


if __name__ == "__main__":
    main()
