#!/usr/bin/env bash
# kaizen UserPromptSubmit hook — re-surface the active discipline
# pins to the agent at every user turn.
#
# When the user picked discipline bundles at session intake (via
# /kaizen:mode or the SessionStart QA), those choices are stored in
# .kaizen/session-mode.json. Without a reminder, the agent forgets
# the pin over a long session. This hook injects a compact block:
#
#   kaizen disciplines pinned: kiss, dry, tdd
#     - kiss: keep it simple — fewest moving parts wins
#     - dry:  no duplication — extract on 2nd repetition, not 1st
#     - tdd:  TDD — RED first, GREEN clean, refactor third
#
# Empty (no-op) when no session-mode is set or no skills pinned.
# Token cost: ~80-300 bytes per prompt depending on pin count.
#
# Bypass: KAIZEN_SKILLS_REMINDER_DISABLE=1

set -uo pipefail

[ "${KAIZEN_SKILLS_REMINDER_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Resolve repo root — reminder is only relevant inside a kaizen project.
REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
cd "$REPO" || { echo '{}'; exit 0; }

# Skip when no session-mode is set.
[ -f ".kaizen/session-mode.json" ] || { echo '{}'; exit 0; }

# Get the active-skills reminder block (single python3 spawn — reads
# state, looks up descriptions, emits the formatted block, or empty
# string when no skills pinned).
REMINDER=$(python3 "$PLUGIN_ROOT/skills/workflow/scripts/session_mode.py" reminder 2>/dev/null)

# Empty stdout → nothing to inject.
[ -z "$REMINDER" ] && { echo '{}'; exit 0; }

# Emit additionalContext so the agent sees the reminder before
# composing its response to the user's prompt.
REMINDER="$REMINDER" python3 -c "
import json, os
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'UserPromptSubmit',
        'additionalContext': os.environ['REMINDER'],
    },
}))
"
