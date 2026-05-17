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

## Activation + modes

  KAIZEN_ATOMIC_WRITE_ENABLE=1   ← opt-in (default OFF — no hook fire)
  KAIZEN_ATOMIC_WRITE_DISABLE=1  ← legacy disable knob (still honored)
  KAIZEN_ATOMIC_WRITE_MODE=note     ← (default) advisory + CC's Write runs
  KAIZEN_ATOMIC_WRITE_MODE=enforce  ← deny CC's Write (legacy strict mode)

### note mode (default — recommended)

Pre-writes atomically, emits `additionalContext` with metadata + flag,
lets CC's Write run normally. CC overwrites our atomic write
(last-writer-wins) — atomic guarantee is REAL for the window between
our pre-write and CC's write. Zero `Error:` noise in CC UI.

### enforce mode (legacy strict)

Pre-writes atomically + `permissionDecision: deny` so CC's Write is
blocked. The agent sees an `Error:` (CC always renders deny that way)
but the deny REASON explains the write succeeded — the agent should
treat the error as success-by-other-means. Trades UX noise for true
single-writer atomicity.
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


_VALID_MODES = ("note", "enforce")


def main() -> int:
    # Hook is OFF unless ENABLE=1 explicitly set.
    enabled = os.environ.get("KAIZEN_ATOMIC_WRITE_ENABLE", "") == "1"
    disabled = os.environ.get("KAIZEN_ATOMIC_WRITE_DISABLE", "") == "1"
    if not enabled or disabled:
        return _emit({})

    # Mode selector — default "note" (advisory, no Error noise);
    # set "enforce" for the legacy behaviour (deny CC's Write so the
    # agent must use kaizen-write or treat the deny as success-by-other-
    # means). Unknown modes fall back to "note" (safe default).
    mode = os.environ.get("KAIZEN_ATOMIC_WRITE_MODE", "note").lower()
    if mode not in _VALID_MODES:
        mode = "note"

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

    # Always pre-write atomically when enabled — both modes share this.
    try:
        _atomic.atomic_write(path, content)
    except OSError as exc:
        # Same failure shape across both modes: surface as a note,
        # let CC's Write attempt (no deny — no Error noise either way).
        return _emit({
            "hookSpecificOutput": {
                "hookEventName":     "PreToolUse",
                "additionalContext": (
                    f"[atomic-write] atomic-pre-write failed ({exc!s}); "
                    f"CC's Write runs without atomic guarantee."
                ),
            },
        })

    if mode == "enforce":
        # Legacy mode: deny CC's Write — the file is already written
        # atomically so the agent should treat the deny as success.
        # NOTE: renders as `Error:` in CC UI — that's the cost of
        # enforce mode (single-writer atomicity guarantee).
        return _emit({
            "hookSpecificOutput": {
                "hookEventName":             "PreToolUse",
                "permissionDecision":        "deny",
                "permissionDecisionReason": (
                    f"[atomic-write/enforce] wrote {path} ({size}b) "
                    f"atomically via _atomic.atomic_write. The file is "
                    f"on disk with the requested content — treat this "
                    f"deny as SUCCESS. Switch to advisory mode: "
                    f"export KAIZEN_ATOMIC_WRITE_MODE=note."
                ),
            },
        })

    # Default mode: "note" — advisory only, CC's Write runs normally.
    return _emit({
        "hookSpecificOutput": {
            "hookEventName":     "PreToolUse",
            "additionalContext": (
                f"[atomic-write/note] {path} ({size}b) — pre-written via "
                f"_atomic.atomic_write (tempfile+os.replace). CC's Write "
                f"runs on top (last-writer-wins). "
                f"Strict single-writer: export KAIZEN_ATOMIC_WRITE_MODE=enforce. "
                f"Disable: KAIZEN_ATOMIC_WRITE_DISABLE=1."
            ),
        },
    })


if __name__ == "__main__":
    raise SystemExit(main())
