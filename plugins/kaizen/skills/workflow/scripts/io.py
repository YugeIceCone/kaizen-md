#!/usr/bin/env python3
"""kaizen-io — atomic read/write CLI that mimics CC Read/Write syntax.

Designed as a drop-in replacement for CC's native Read + Write tools
when you want:
  - Atomic writes (tempfile + os.replace)
  - Batch operations (5+ files in ONE Bash roundtrip)
  - Same `{file_path, content}` input shape the agent already knows

## Subcommands

  read <file_path> [--json]                          single read
  write <file_path> [--content X | --stdin] [--json] single atomic write
  batch --json                                       batch from stdin JSON

## Batch shape

Stdin is a JSON array of ops. Each op:

  {"op": "read",  "file_path": "/abs/path"}
  {"op": "write", "file_path": "/abs/path", "content": "..."}
  {"op": "write_bytes", "file_path": "/abs/path", "bytes_base64": "..."}

Result is a JSON array, same length + order, each entry:

  {"op": "read",  "file_path": "...", "ok": true,  "content": "..."}
  {"op": "write", "file_path": "...", "ok": true,  "bytes": 42}
  {"op": "read",  "file_path": "...", "ok": false, "error": "..."}

Ops run in parallel via asyncio (atomic_write is sync but cheap; the
parallelism saves wall-time on N>1 ops by overlapping fsync).

## Why this exists

CC's native Write is non-atomic (truncate-then-write). For sensitive
overwrites or batch operations spanning many files, `kaizen-io batch`
gives:
  - Atomic guarantee (each write is tempfile+rename)
  - Single tool call for N ops (vs N Write calls = N roundtrips)
  - Mixed read+write batches (e.g., read 3 configs, write 2 derived files)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path


_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _atomic  # noqa: E402


def _read_one(path: str) -> dict:
    p = Path(path).expanduser()
    try:
        content = p.read_text(encoding="utf-8")
        return {"op": "read", "file_path": path, "ok": True,
                "content": content, "bytes": len(content)}
    except OSError as e:
        return {"op": "read", "file_path": path, "ok": False,
                "error": str(e)}


def _write_one(path: str, content: str) -> dict:
    try:
        _atomic.atomic_write(path, content)
        return {"op": "write", "file_path": path, "ok": True,
                "bytes": len(content)}
    except OSError as e:
        return {"op": "write", "file_path": path, "ok": False,
                "error": str(e)}


def _write_bytes_one(path: str, b64: str) -> dict:
    try:
        payload = base64.b64decode(b64)
        _atomic.atomic_write_bytes(path, payload)
        return {"op": "write_bytes", "file_path": path, "ok": True,
                "bytes": len(payload)}
    except (OSError, ValueError, base64.binascii.Error) as e:
        return {"op": "write_bytes", "file_path": path, "ok": False,
                "error": str(e)}


async def _run_op(op: dict) -> dict:
    """Dispatch a single op via asyncio.to_thread (atomic ops are sync IO)."""
    kind = op.get("op")
    path = op.get("file_path")
    if not path:
        return {"op": kind, "ok": False, "error": "missing file_path"}
    if kind == "read":
        return await asyncio.to_thread(_read_one, path)
    if kind == "write":
        content = op.get("content")
        if content is None:
            return {"op": kind, "file_path": path, "ok": False,
                    "error": "missing content"}
        return await asyncio.to_thread(_write_one, path, content)
    if kind == "write_bytes":
        b64 = op.get("bytes_base64")
        if not b64:
            return {"op": kind, "file_path": path, "ok": False,
                    "error": "missing bytes_base64"}
        return await asyncio.to_thread(_write_bytes_one, path, b64)
    return {"op": kind, "file_path": path, "ok": False,
            "error": f"unknown op: {kind!r}"}


async def _run_batch(ops: list[dict]) -> list[dict]:
    """Two-phase parallel dispatch — preserves order in the result.

    Phase 1: all WRITE ops run in parallel (atomic, no ordering needed
             between them since each writes to a distinct path).
    Phase 2: all READ ops run in parallel AFTER writes complete (so a
             batch mixing 'write a; read a' works correctly).

    Result is returned in the same order as input — phase ordering is
    an internal optimisation, not visible in the output.
    """
    # Track indices to restore original order at the end
    write_indices = [i for i, op in enumerate(ops)
                     if op.get("op") in ("write", "write_bytes")]
    read_indices = [i for i, op in enumerate(ops)
                    if op.get("op") == "read"]
    other_indices = [i for i, op in enumerate(ops)
                     if i not in set(write_indices) | set(read_indices)]

    results: list[dict] = [None] * len(ops)  # type: ignore[list-item]

    # Phase 1: writes (parallel within phase)
    if write_indices:
        write_results = await asyncio.gather(
            *(_run_op(ops[i]) for i in write_indices))
        for i, r in zip(write_indices, write_results):
            results[i] = r

    # Phase 2: reads (parallel within phase; sees writes from phase 1)
    if read_indices:
        read_results = await asyncio.gather(
            *(_run_op(ops[i]) for i in read_indices))
        for i, r in zip(read_indices, read_results):
            results[i] = r

    # Phase 3: unknown ops (parallel; error-shape)
    if other_indices:
        other_results = await asyncio.gather(
            *(_run_op(ops[i]) for i in other_indices))
        for i, r in zip(other_indices, other_results):
            results[i] = r

    return results


def _cmd_read(args) -> int:
    paths = args.file_path
    # Back-compat: single positional arg → identical to pre-multi-arg behavior
    # (raw content to stdout; --json returns ONE envelope, not a length-1 array).
    if len(paths) == 1:
        r = _read_one(paths[0])
        if args.json:
            print(json.dumps(r))
        else:
            if r["ok"]:
                print(r["content"], end="")
            else:
                sys.stderr.write(f"[kaizen-io read] {r['error']}\n")
        return 0 if r["ok"] else 1

    # Multi-arg: parallel reads via _run_batch (same primitive `batch` uses).
    ops = [{"op": "read", "file_path": p} for p in paths]
    results = asyncio.run(_run_batch(ops))
    if args.json:
        print(json.dumps(results))
    else:
        # Concatenated form with path separators — readable for human consumers
        # and for "feed N files into one Read call" workflows.
        for r in results:
            print(f"=== {r.get('file_path', '?')} ===")
            if r.get("ok"):
                print(r.get("content", ""), end="")
            else:
                print(f"[error] {r.get('error', 'unknown')}")
    return 0 if all(r.get("ok") for r in results) else 1


def _cmd_write(args) -> int:
    if args.stdin:
        content = sys.stdin.read()
    elif args.content is not None:
        content = args.content
    else:
        sys.stderr.write("[kaizen-io write] need --content or --stdin\n")
        return 2
    r = _write_one(args.file_path, content)
    if args.json:
        print(json.dumps(r))
    else:
        if r["ok"]:
            print(f"[kaizen-io write] {args.file_path} ({r['bytes']}b)")
        else:
            sys.stderr.write(f"[kaizen-io write] {r['error']}\n")
    return 0 if r["ok"] else 1


def _cmd_batch(args) -> int:
    try:
        ops = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[kaizen-io batch] invalid JSON on stdin: {e}\n")
        return 2
    if not isinstance(ops, list):
        sys.stderr.write("[kaizen-io batch] stdin must be a JSON array of ops\n")
        return 2
    results = asyncio.run(_run_batch(ops))
    # Summary on stderr; full results on stdout as JSON
    ok = sum(1 for r in results if r.get("ok"))
    bad = len(results) - ok
    print(json.dumps(results, indent=2 if args.pretty else None))
    sys.stderr.write(f"[kaizen-io batch] {len(results)} op(s) — "
                      f"{ok} ok, {bad} failed\n")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-io",
        description="Atomic read/write with batch parallel ops.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("read",
                          help="read 1+ files (parallel when N>1; back-compat "
                               "single-arg returns raw content)")
    pr.add_argument("file_path", nargs="+",
                     help="one or more file paths (parallel reads when 2+)")
    pr.add_argument("--json", action="store_true",
                     help="JSON output (single envelope when N=1, "
                          "array of envelopes when N>1)")
    pr.set_defaults(func=_cmd_read)

    pw = sub.add_parser("write", help="single atomic write")
    pw.add_argument("file_path")
    src = pw.add_mutually_exclusive_group()
    src.add_argument("--content", default=None,
                      help="inline content")
    src.add_argument("--stdin", action="store_true",
                      help="read content from stdin")
    pw.add_argument("--json", action="store_true")
    pw.set_defaults(func=_cmd_write)

    pb = sub.add_parser("batch", help="parallel batch from stdin JSON array")
    pb.add_argument("--pretty", action="store_true",
                     help="pretty-print result JSON")
    pb.set_defaults(func=_cmd_batch)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
