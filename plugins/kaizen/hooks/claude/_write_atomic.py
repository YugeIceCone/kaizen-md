#!/usr/bin/env python3
"""kaizen atomic-Write hook backing — intercept CC Write, route through _atomic.

Reads the PreToolUse event JSON on stdin. When the tool is `Write`,
performs an atomic write via _atomic.atomic_write (tempfile + os.replace)
and emits a permission-deny decision so the agent skips the original
Write. The file is on disk with the requested content either way.

On any failure, falls through (empty decision) so the original Write
runs as a fallback — atomicity is a "best effort" upgrade, never a
blocker.

## Why a wrapper

CC's built-in Write uses `open(path, "w")` semantics — truncate then
write. Power loss between the truncate and write leaves an empty file.
`_atomic.atomic_write` writes to a sibling tempfile then `os.replace`
(POSIX atomic rename) so the target is either fully old or fully new.

## Bypass

  KAIZEN_ATOMIC_WRITE_DISABLE=1  ← global escape valve
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "workflow" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import _atomic  # noqa: E402


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0


def main() -> int:
    if os.environ.get("KAIZEN_ATOMIC_WRITE_DISABLE", "") == "1":
        return _emit({})

    try:
        evt = json.load(sys.stdin)
    except json.JSONDecodeError:
        return _emit({})

    if evt.get("tool_name") != "Write":
        return _emit({})

    inp = evt.get("tool_input") or {}
    path = inp.get("file_path")
    content = inp.get("content")
    if not path or content is None:
        return _emit({})

    try:
        _atomic.atomic_write(path, content)
    except OSError as exc:
        # Atomic write failed (permission / disk full / dir gone) —
        # let CC's original Write try; surface the cause for the agent.
        return _emit({
            "hookSpecificOutput": {
                "hookEventName":     "PreToolUse",
                "additionalContext": (
                    f"kaizen-atomic-write: atomic path failed ({exc!s}); "
                    f"falling through to CC's Write"
                ),
            },
        })

    return _emit({
        "hookSpecificOutput": {
            "hookEventName":             "PreToolUse",
            "permissionDecision":        "deny",
            "permissionDecisionReason": (
                f"kaizen-atomic-write: wrote {path} atomically via "
                f"_atomic.atomic_write (tempfile + os.replace, POSIX "
                f"atomic rename). The file has been written with the "
                f"requested content; treat this as success and proceed. "
                f"Bypass with KAIZEN_ATOMIC_WRITE_DISABLE=1."
            ),
        },
    })


if __name__ == "__main__":
    raise SystemExit(main())
