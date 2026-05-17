"""kaizen userprompt_skill_suggest — UserPromptSubmit helper.

Reads CC's event JSON from stdin, extracts the prompt, runs
skill_suggest.match_prompt against the skills/ catalog, emits the
additionalContext envelope when matches exist.

Single python3 spawn (same shape as the other consolidated hot-path
hooks). The shell wrapper just delegates.

Bypass: KAIZEN_SKILL_SUGGEST_DISABLE=1 (also checked at shell level
to avoid the python3 spawn entirely when disabled).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if os.environ.get("KAIZEN_SKILL_SUGGEST_DISABLE") == "1":
        print("{}")
        return 0

    try:
        event = json.load(sys.stdin)
    except Exception:
        print("{}")
        return 0

    prompt = event.get("prompt") or event.get("user_prompt") or ""
    if not prompt:
        print("{}")
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import skill_suggest as _ss
    except ImportError:
        print("{}")
        return 0

    try:
        matches = _ss.match_prompt(str(prompt), max_results=3)
    except Exception:
        print("{}")
        return 0

    if not matches:
        print("{}")
        return 0

    lines = ["kaizen-skill-suggest: prompt matches these skills "
              "(consider Load Skill(name)):"]
    for m in matches:
        triggers = ", ".join(m["matched"][:5])
        lines.append(
            f"  - {m['name']} ({m['match_count']}/{m['trigger_count']}"
            f" triggers): {triggers}"
        )
    body = "\n".join(lines)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName":     "UserPromptSubmit",
            "additionalContext": body,
        },
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
