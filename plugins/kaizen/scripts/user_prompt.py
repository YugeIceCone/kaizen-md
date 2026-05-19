#!/usr/bin/env python3
"""kaizen user_prompt — UserPromptSubmit hook port of upstream user_prompt.js.

Reads the user's prompt from stdin, detects brain-dump keywords, and
if matched, injects the capture-routing context as
``hookSpecificOutput.additionalContext`` for Claude to consume. No-op
otherwise (prints nothing, exit 0).

Bypass: REMEMBER_PROCESSING=1 (silent no-op).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from build_context import build_capture_context  # noqa: E402
from session_start import brain_root, load_config  # noqa: E402


def main() -> int:
    if os.environ.get("REMEMBER_PROCESSING") == "1":
        return 0
    try:
        input_text = sys.stdin.read()
    except Exception:  # noqa: BLE001 — best-effort, never raise from a hook
        return 0
    if not input_text:
        return 0

    brain = brain_root()
    if not brain.is_dir():
        return 0

    config = load_config()
    keywords = config.get("session", {}).get("brain_dump_keywords") or [
        "save this", "remember this", "brain dump", "note to self",
        "capture this", "save to brain", "write to brain", "add to brain",
        "salvează", "notează", "reține",
    ]

    # Hook payload arrives as JSON on stdin (Claude Code shape). Older
    # invocations passed the raw prompt; handle both shapes.
    prompt_text = input_text
    try:
        event = json.loads(input_text)
        if isinstance(event, dict):
            prompt_text = (
                event.get("prompt")
                or event.get("user_prompt")
                or event.get("message")
                or input_text
            )
    except json.JSONDecodeError:
        pass

    lower = (prompt_text or "").lower()
    if not any(k in lower for k in keywords):
        return 0

    plugin_root = _SCRIPT_DIR.parent
    context = build_capture_context(brain, plugin_root)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        },
    }
    print(json.dumps(output, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
