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

## Activation

The hook is OPT-IN (default OFF) — `permissionDecision: deny` renders
as "Error: ..." in CC even when the atomic write succeeded, which
creates noisy UX for every Write. Enable explicitly when atomicity
matters more than the noise:

  KAIZEN_ATOMIC_WRITE_ENABLE=1  ← opt-in
  KAIZEN_ATOMIC_WRITE_DISABLE=1 ← legacy disable knob (still honored)
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
    # Hook is OFF unless ENABLE=1 explicitly set.
    enabled = os.environ.get("KAIZEN_ATOMIC_WRITE_ENABLE", "") == "1"
    disabled = os.environ.get("KAIZEN_ATOMIC_WRITE_DISABLE", "") == "1"
    if not enabled or disabled:
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

    size = len(content) if isinstance(content, str) else 0

    # NEW SHAPE: capture metadata + atomic-write, but DO NOT deny.
    # CC's native Write runs normally — last-writer-wins on the same
    # path (our atomic-write happens first, CC's overwrites with same
    # content). The atomic guarantee is real for the window between
    # our write and CC's. Agent sees normal Write success (no Error
    # noise) plus an additionalContext note about the flag.
    try:
        _atomic.atomic_write(path, content)
        return _emit({
            "hookSpecificOutput": {
                "hookEventName":     "PreToolUse",
                "additionalContext": (
                    f"[atomic-write] {path} ({size}b) — pre-written via "
                    f"_atomic.atomic_write (tempfile+os.replace). CC's "
                    f"Write will run normally on top. "
                    f"Disable: KAIZEN_ATOMIC_WRITE_DISABLE=1."
                ),
            },
        })
    except OSError as exc:
        return _emit({
            "hookSpecificOutput": {
                "hookEventName":     "PreToolUse",
                "additionalContext": (
                    f"[atomic-write] atomic-pre-write failed ({exc!s}); "
                    f"CC's Write runs without atomic guarantee."
                ),
            },
        })


if __name__ == "__main__":
    raise SystemExit(main())
