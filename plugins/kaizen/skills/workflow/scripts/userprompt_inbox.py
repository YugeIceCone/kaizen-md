"""kaizen userprompt_inbox — consolidated UserPromptSubmit inbox capture.

Reads stdin once, extracts PROMPT + SESSION_ID, calls inbox.capture
and inbox.set_turn_starter directly. One python3 spawn instead of 4
(extract prompt + extract session + capture + set-turn-starter).

Mid-turn prompts (typed while Claude is busy) do not overwrite the
turn-starter sentinel — they surface normally on the next
PostToolUse drain. The Stop hook clears the sentinel at turn end.

Bypass: KAIZEN_INBOX_DISABLE=1 (silent no-op).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if os.environ.get("KAIZEN_INBOX_DISABLE") == "1":
        return 0

    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    prompt = (
        event.get("prompt")
        or event.get("user_prompt")
        or event.get("message")
        or ""
    )
    if not prompt:
        return 0

    session_id = event.get("session_id", "") or ""

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import inbox as _inbox
    except ImportError:
        return 0

    try:
        captured_path = _inbox.capture(str(prompt), str(session_id))
    except Exception:
        return 0

    # Mark this as the turn-starter ONLY if no sentinel exists.
    # set_turn_starter is idempotent + no-ops when a sentinel is
    # already present (a mid-turn typed prompt mustn't overwrite the
    # original turn-starter).
    try:
        _inbox.set_turn_starter(str(captured_path))
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
