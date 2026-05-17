"""Content-addressed blob store for kaizen generated artifacts (v1.30.0+).

Every immutable artifact kaizen produces — backup tarballs, observe snapshots,
rotated trace files, schema yamls — flows through this store. Each blob is
named by its sha256 hex digest and lives at:

    ~/.claude/.kaizen/blobs/<sha256-hex>

A single global manifest at `~/.claude/.kaizen/data/manifest.json` maps every
hash to metadata: kind, original name, creation time, size, and the list of
logical refs that point at it. Logical paths (e.g.
`~/.claude/.kaizen/backups/<repo-slug>/<UTC>.tar.gz`) become **symlinks** into
the blob store — same UX as before but every byte is content-addressed.

## Why bother

1. **Migrations are exact, not heuristic.** "is this artifact already in the
   canonical location?" → hash both, compare. No `[ -e ]` fuzzy match.
2. **Dedup.** Two backups with identical content collapse to one blob.
3. **Integrity.** `kaizen:doctor` can recompute hashes and compare to the
   manifest; tamper / corruption surfaces immediately.
4. **Restore by hash.** Backup id is a label; the sha is the truth.
5. **Cross-machine sync.** `rsync --link-dest` against a peer's blob store
   naturally dedups.

## API

    put_file(path: Path, kind: str, name: str | None = None,
             ref: Path | None = None) -> str
        Move a file into the blob store. Returns the sha256 hex.

    put_bytes(data: bytes, kind: str, name: str) -> str
        Stream bytes into the blob store. Returns the sha256 hex.

    get(sha: str) -> Path
        Resolve a sha to its blob path. Raises KeyError if absent.

    sha256_file(path: Path) -> str
        Compute the sha of a file without ingesting it. Streaming (chunked).

    sha256_bytes(data: bytes) -> str
        Compute the sha of an in-memory blob.

    add_ref(sha: str, ref_path: Path, context: str = "") -> None
        Register an additional logical ref pointing at an existing blob.

    list_blobs(kind: str | None = None) -> list[dict]
        Return all manifest entries, optionally filtered by kind.

    manifest() -> dict
        Read-only access to the raw manifest dict.

## Pre-deletion safety

This module NEVER rms a blob. The manifest grows monotonically. If you need
to garbage-collect orphan blobs, that's a separate, gated tool (TBD).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import _paths as _p  # noqa: E402

# ─── Storage layout ──────────────────────────────────────────────────

BLOBS_DIR = _p.KAIZEN_USER_DIR / "blobs"
MANIFEST_FILE = _p.KAIZEN_USER_DIR / "manifest.json"
MANIFEST_LOCK = _p.KAIZEN_USER_DIR / "manifest.lock"

MANIFEST_VERSION = 1
CHUNK_SIZE = 1 << 20  # 1 MiB streaming chunk


# ─── Manifest cross-process lock (M1) ────────────────────────────────


@contextlib.contextmanager
def _manifest_lock():
    """fcntl.flock(LOCK_EX) on a sibling lockfile.

    Serialises read-modify-write across concurrent processes (e.g. user-
    invoked /kaizen:backup create racing the daemon's hygiene pass). The
    lockfile itself is never read; its handle is the lock token.

    Why a separate lockfile (not manifest.json itself)? Because
    `_save_manifest` uses `os.replace` to swap the file atomically, which
    INVALIDATES any fd held against the old inode. A sibling lockfile is
    never replaced, so its fd's lock survives every manifest write.
    """
    MANIFEST_LOCK.parent.mkdir(parents=True, exist_ok=True)
    # Open in append mode so the lockfile is created if missing without
    # truncating it.
    f = open(MANIFEST_LOCK, "a")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()

# ─── Manifest I/O ────────────────────────────────────────────────────


def _load_manifest() -> dict:
    if not MANIFEST_FILE.exists():
        return {"version": MANIFEST_VERSION, "blobs": {}}
    try:
        data = json.loads(MANIFEST_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        # Corrupt manifest — start fresh, preserve the broken one for
        # forensic inspection. Pre-deletion belief: never silently rm.
        # L1: if a peer process raced us and already renamed the file,
        # the rename here raises FileNotFoundError; fall through to the
        # empty-default. Other OS errors are also tolerated — start fresh.
        backup = MANIFEST_FILE.with_suffix(
            f".json.broken-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        try:
            MANIFEST_FILE.rename(backup)
        except (FileNotFoundError, OSError):
            pass
        return {"version": MANIFEST_VERSION, "blobs": {}}
    data.setdefault("version", MANIFEST_VERSION)
    data.setdefault("blobs", {})
    return data


def _save_manifest(data: dict) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, MANIFEST_FILE)


def manifest() -> dict:
    """Return the full manifest (read-only — do not mutate the returned dict)."""
    return _load_manifest()


# ─── Hashing ─────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    """Compute sha256 hex of a file, streaming in CHUNK_SIZE blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─── Blob path resolution ────────────────────────────────────────────


def _blob_path(sha: str) -> Path:
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
        raise ValueError(f"invalid sha256 hex: {sha!r}")
    return BLOBS_DIR / sha


# ─── Public API ──────────────────────────────────────────────────────


def get(sha: str) -> Path:
    """Resolve a sha to its blob path. Raises KeyError if absent."""
    p = _blob_path(sha)
    if not p.exists():
        raise KeyError(f"blob {sha} not in store at {p}")
    return p


def has(sha: str) -> bool:
    return _blob_path(sha).exists()


def put_file(
    path: Path,
    kind: str,
    name: str | None = None,
    ref: Path | None = None,
    context: str = "",
) -> str:
    """Ingest `path` into the blob store. Returns the sha256 hex.

    The source file is **moved** (not copied) if it's outside the blob
    store; if it's already inside (or the blob already exists with the
    same content), the source is left intact and the existing blob is
    reused. Manifest is updated atomically.

    If `ref` is given, a symlink is created at that path pointing at the
    blob, and the ref is recorded in the manifest's refs list."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    sha = sha256_file(path)
    blob = _blob_path(sha)
    BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    if not blob.exists():
        # shutil.move handles cross-device (tmpfs → ext4) by copy + unlink,
        # whereas os.replace requires same filesystem.
        shutil.move(str(path), str(blob))
    else:
        # Blob already in store — drop the duplicate.
        if path.resolve() != blob.resolve():
            path.unlink()
    _record(sha, kind, name or path.name, blob.stat().st_size, ref, context)
    if ref is not None:
        _materialise_ref(sha, ref)
    return sha


def put_bytes(
    data: bytes,
    kind: str,
    name: str,
    ref: Path | None = None,
    context: str = "",
) -> str:
    sha = sha256_bytes(data)
    blob = _blob_path(sha)
    BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    if not blob.exists():
        tmp = blob.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, blob)
    _record(sha, kind, name, len(data), ref, context)
    if ref is not None:
        _materialise_ref(sha, ref)
    return sha


def add_ref(sha: str, ref_path: Path, context: str = "") -> None:
    """Register an additional logical ref + materialise the symlink."""
    if not has(sha):
        raise KeyError(f"blob {sha} not in store")
    with _manifest_lock():
        data = _load_manifest()
        entry = data["blobs"].setdefault(sha, {})
        refs = entry.setdefault("refs", [])
        rel = str(ref_path)
        if not any(r.get("path") == rel for r in refs):
            refs.append({"path": rel, "context": context, "added": _now()})
            _save_manifest(data)
    _materialise_ref(sha, ref_path)


def list_blobs(kind: str | None = None) -> list[dict]:
    data = _load_manifest()
    entries: list[dict] = []
    for sha, meta in data["blobs"].items():
        if kind is not None and meta.get("kind") != kind:
            continue
        entries.append({"sha": sha, **meta})
    return entries


# ─── Helpers ─────────────────────────────────────────────────────────


def _record(
    sha: str,
    kind: str,
    name: str,
    size: int,
    ref: Path | None,
    context: str,
) -> None:
    with _manifest_lock():
        data = _load_manifest()
        entry = data["blobs"].setdefault(
            sha,
            {
                "kind": kind,
                "name": name,
                "size": size,
                "created": _now(),
                "refs": [],
            },
        )
        # Update fields that may have changed (size shouldn't, but defensive).
        entry["kind"] = entry.get("kind") or kind
        entry["size"] = size
        if ref is not None:
            rel = str(ref)
            refs = entry.setdefault("refs", [])
            if not any(r.get("path") == rel for r in refs):
                refs.append({"path": rel, "context": context, "added": _now()})
        _save_manifest(data)


def _materialise_ref(sha: str, ref_path: Path) -> None:
    """Create (or replace) a symlink at ref_path pointing at the blob."""
    ref_path = Path(ref_path)
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    blob = _blob_path(sha)
    if ref_path.is_symlink() or ref_path.exists():
        ref_path.unlink()
    ref_path.symlink_to(blob)


from _time import iso  # M5 dedup


def _now() -> str:
    return iso(precision="seconds")


# ─── Self-test ───────────────────────────────────────────────────────


def _self_test() -> None:
    """RED / GREEN smoke test — exercised on import via `python3 _blobs.py`."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Patch storage to a sandbox.
        global BLOBS_DIR, MANIFEST_FILE  # noqa: PLW0603 — test-only patch
        BLOBS_DIR = td_path / "blobs"
        MANIFEST_FILE = td_path / "manifest.json"

        # 1. put_bytes round-trip.
        sha1 = put_bytes(b"hello world", kind="test", name="hello.txt")
        assert sha1 == hashlib.sha256(b"hello world").hexdigest()
        assert get(sha1).read_bytes() == b"hello world"
        assert has(sha1)

        # 2. Idempotent put — same content → same sha, single blob.
        sha2 = put_bytes(b"hello world", kind="test", name="hello.txt")
        assert sha1 == sha2
        assert len(list(BLOBS_DIR.iterdir())) == 1

        # 3. put_file moves the source and produces a blob.
        src = td_path / "src.txt"
        src.write_bytes(b"streamed file content")
        sha3 = put_file(src, kind="test", name="src.txt")
        assert not src.exists(), "source should have been moved into the blob store"
        assert get(sha3).read_bytes() == b"streamed file content"

        # 4. Ref materialisation creates a symlink.
        ref = td_path / "logical" / "myname.txt"
        sha4 = put_bytes(b"with a ref", kind="test", name="r.txt", ref=ref, context="test-ref")
        assert ref.is_symlink()
        assert ref.resolve() == get(sha4).resolve()

        # 5. add_ref adds a second logical pointer at the same blob.
        ref2 = td_path / "logical" / "alias.txt"
        add_ref(sha4, ref2, context="alias")
        assert ref2.is_symlink()
        assert ref2.resolve() == ref.resolve()
        entry = manifest()["blobs"][sha4]
        assert len(entry["refs"]) == 2

        # 6. list_blobs filters by kind.
        entries = list_blobs(kind="test")
        shas = {e["sha"] for e in entries}
        assert sha1 in shas and sha3 in shas and sha4 in shas

        # 7. sha256_file streaming.
        big = td_path / "big.bin"
        big.write_bytes(b"x" * (CHUNK_SIZE + 1))  # > 1 MiB
        h_stream = sha256_file(big)
        h_ref = hashlib.sha256(b"x" * (CHUNK_SIZE + 1)).hexdigest()
        assert h_stream == h_ref

        # 8. invalid sha raises.
        try:
            _blob_path("not-a-real-sha")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for bad sha")

    print("✓ _blobs.py self-test pass (8 / 8)")


# ─── CLI ─────────────────────────────────────────────────────────────


def _cli(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="_blobs",
        description="Content-addressed blob store for kaizen artifacts.",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_put = sub.add_parser("put", help="ingest a file into the blob store")
    p_put.add_argument("path", type=Path)
    p_put.add_argument("--kind", required=True)
    p_put.add_argument("--name", default=None)
    p_put.add_argument("--ref", type=Path, default=None,
                       help="materialise a symlink at this path pointing at the blob")
    p_put.add_argument("--context", default="")

    p_sha = sub.add_parser("sha", help="compute sha256 of a file without ingesting")
    p_sha.add_argument("path", type=Path)

    p_get = sub.add_parser("get", help="print the absolute blob path for a sha")
    p_get.add_argument("sha")

    p_info = sub.add_parser("info", help="print manifest metadata for a sha")
    p_info.add_argument("sha")

    p_list = sub.add_parser("list", help="list blobs (filter by --kind)")
    p_list.add_argument("--kind", default=None)
    p_list.add_argument("--json", action="store_true", help="emit JSON instead of human-readable")

    p_addref = sub.add_parser("add-ref", help="add a logical ref + symlink to an existing blob")
    p_addref.add_argument("sha")
    p_addref.add_argument("ref", type=Path)
    p_addref.add_argument("--context", default="")

    sub.add_parser("test", help="run the self-test")

    args = ap.parse_args(argv)

    if args.cmd is None:
        ap.print_help()
        return 0
    if args.cmd == "put":
        sha = put_file(args.path, kind=args.kind, name=args.name,
                       ref=args.ref, context=args.context)
        print(sha)
        return 0
    if args.cmd == "sha":
        print(sha256_file(args.path))
        return 0
    if args.cmd == "get":
        try:
            print(get(args.sha))
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "info":
        m = manifest()
        entry = m["blobs"].get(args.sha)
        if not entry:
            print(f"no manifest entry for {args.sha}", file=sys.stderr)
            return 1
        print(json.dumps({"sha": args.sha, **entry}, indent=2))
        return 0
    if args.cmd == "list":
        entries = list_blobs(kind=args.kind)
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            for e in entries:
                short = e["sha"][:12]
                kind = e.get("kind", "-")
                name = e.get("name", "-")
                size = e.get("size", 0)
                created = e.get("created", "-")
                refs = e.get("refs", [])
                print(f"{short}  {kind:12}  {size:>10}  {created}  {name}  refs={len(refs)}")
        return 0
    if args.cmd == "add-ref":
        try:
            add_ref(args.sha, args.ref, context=args.context)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "test":
        _self_test()
        return 0
    return 2


if __name__ == "__main__":
    # Default behaviour when called with no args is the self-test (back-compat
    # with `python3 _blobs.py` from the unit-test era).
    if len(sys.argv) == 1:
        _self_test()
    else:
        sys.exit(_cli(sys.argv[1:]))
