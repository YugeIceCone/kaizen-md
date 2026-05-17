"""kaizen intent_userprompt — consolidated UserPromptSubmit intent
matcher. Reads stdin once, extracts prompt text, runs intent.suggest
matching logic in-process, emits the hook-decision JSON.

Replaces 3 python3 spawns in intent-userprompt.sh:
  1. extract prompt from event JSON
  2. python3 intent.py suggest --json (full subprocess)
  3. python3 -c to format hook decision

Output:
  {"systemMessage": "kaizen-intent: <id> (conf=N.NN) — <suggestion>"}
  {} when no match (or disabled / malformed input)

Bypass: KAIZEN_INTENT_DISABLE=1.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


_EMPTY = "{}"


def main() -> int:
    if os.environ.get("KAIZEN_INTENT_DISABLE") == "1":
        print(_EMPTY)
        return 0

    try:
        event = json.load(sys.stdin)
    except Exception:
        print(_EMPTY)
        return 0

    # CC may shape the prompt as 'prompt' or 'user_prompt'
    prompt = event.get("prompt") or event.get("user_prompt") or ""
    if not prompt:
        print(_EMPTY)
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import intent as _intent
    except ImportError:
        print(_EMPTY)
        return 0

    try:
        intents = _intent._load_intents()
    except (FileNotFoundError, RuntimeError):
        print(_EMPTY)
        return 0

    best = None
    best_conf = -1.0
    for i in intents:
        if _intent._intent_matches(i, str(prompt), []):
            conf = _intent._intent_confidence(i)
            if conf > best_conf:
                best = i
                best_conf = conf

    if best is None:
        print(_EMPTY)
        return 0

    action = best.get("action") or {}
    msg = (
        f"kaizen-intent: {best.get('id')} "
        f"(conf={best_conf:.2f}) — "
        f"{action.get('suggest', '<no suggestion>')}"
    )
    print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
