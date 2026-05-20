#!/usr/bin/env bash
# kaizen-intent UserPromptSubmit hook — fire intent suggest on every user
# prompt; emit a systemMessage when a match fires.
#
# Reads CC event JSON on stdin, extracts the `prompt` text, pipes it to
# kaizen-intent suggest, and prints a hook-decision JSON to stdout.
#
# Output:
#   {"systemMessage": "kaizen-intent: <id> (conf=N.NN) — <suggestion>"}
#   {} when no match (or disabled / malformed input)
#
# Bypass: KAIZEN_INTENT_DISABLE=1 (silent no-op)

set -uo pipefail

if [ "${KAIZEN_INTENT_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Single python3 spawn — intent_userprompt.py reads stdin, extracts
# prompt, runs the suggest matching logic in-process, emits the
# hook-decision JSON. Was 3 spawns (extract prompt + intent.py
# subprocess + format hook JSON).
python3 "$PLUGIN_ROOT/scripts/intent/intent_userprompt.py"

exit 0
