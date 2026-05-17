"""kaizen-write — CLI wrapper exposing _atomic to shell consumers.

Lets agents (and shell scripts) atomically write a file from outside
Python. Wraps _atomic.atomic_write / atomic_write_json /
atomic_write_bytes / atomic_append_line with one consistent CLI.

## Examples

    # Write a string atomically
    echo "hello" | kaizen-write --path out.txt --stdin
    kaizen-write --path out.txt --content "hello"

    # Write JSON (validates before writing — invalid JSON aborts)
    echo '{"a":1}' | kaizen-write --path out.json --json-from-stdin

    # Write bytes from base64 (binary content from shell)
    kaizen-write --path blob.bin --bytes-base64 <(base64 < src.bin)

    # Append a line atomically (JSONL stream)
    kaizen-write --path log.jsonl --append-line --content '{"event":1}'

All targets get parent-dir creation. All writes are atomic via
tempfile+os.replace (POSIX guarantee).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

import _atomic  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kaizen-write",
        description="Atomic file writer — wraps _atomic.py for shell consumers.",
    )
    p.add_argument("--path", required=True,
                    help="absolute or relative path to write to")

    src = p.add_mutually_exclusive_group()
    src.add_argument("--content", default=None,
                      help="inline content (string)")
    src.add_argument("--stdin", action="store_true",
                      help="read content from stdin")
    src.add_argument("--json-from-stdin", action="store_true",
                      help="read + validate JSON from stdin; write with sort_keys")
    src.add_argument("--bytes-base64", default=None,
                      help="base64-encoded bytes payload")

    p.add_argument("--append-line", action="store_true",
                    help="append (one line + newline) instead of overwrite")

    args = p.parse_args(argv)
    target = Path(args.path).expanduser()

    # Resolve content from the chosen source
    if args.stdin:
        content = sys.stdin.read()
    elif args.content is not None:
        content = args.content
    elif args.json_from_stdin:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[kaizen-write] invalid JSON: {exc}", file=sys.stderr)
            return 2
        try:
            _atomic.atomic_write_json(target, data)
        except OSError as exc:
            print(f"[kaizen-write] write failed: {exc}", file=sys.stderr)
            return 1
        return 0
    elif args.bytes_base64 is not None:
        try:
            payload = base64.b64decode(args.bytes_base64)
        except (ValueError, base64.binascii.Error) as exc:
            print(f"[kaizen-write] invalid base64: {exc}", file=sys.stderr)
            return 2
        try:
            _atomic.atomic_write_bytes(target, payload)
        except OSError as exc:
            print(f"[kaizen-write] write failed: {exc}", file=sys.stderr)
            return 1
        return 0
    else:
        print("[kaizen-write] one of --content, --stdin, --json-from-stdin, "
              "--bytes-base64 is required", file=sys.stderr)
        return 2

    try:
        if args.append_line:
            _atomic.atomic_append_line(target, content)
        else:
            _atomic.atomic_write(target, content)
    except OSError as exc:
        print(f"[kaizen-write] write failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
