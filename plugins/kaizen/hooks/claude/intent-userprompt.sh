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
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

INPUT=$(cat 2>/dev/null || echo '{}')

# Extract prompt text via python3 (shell can't safely handle multiline
# prompts; one spawn here is acceptable since UserPromptSubmit is rare
# vs PreToolUse).
PROMPT=$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    e = json.load(sys.stdin)
except Exception:
    sys.exit(0)
# CC may shape the prompt field as 'prompt' or under 'user_prompt'
print(e.get('prompt') or e.get('user_prompt') or '')
" 2>/dev/null)

# No prompt → silent no-op
[ -z "$PROMPT" ] && { echo '{}'; exit 0; }

# Call kaizen-intent suggest with the prompt text; parse the envelope
SUGGEST_JSON=$(printf '%s' "$PROMPT" | python3 "$PLUGIN_ROOT/skills/workflow/scripts/intent.py" suggest --json 2>/dev/null || echo '{}')

# Build the hook decision via python (envelope parsing needs JSON)
printf '%s' "$SUGGEST_JSON" | python3 -c "
import json, sys
try:
    env = json.load(sys.stdin)
except Exception:
    print('{}'); sys.exit(0)
intent = (env.get('data') or {}).get('intent')
if not intent:
    print('{}'); sys.exit(0)
act = intent.get('action') or {}
msg = (
    f\"kaizen-intent: {intent.get('id')} \"
    f\"(conf={intent.get('confidence', 0):.2f}) — \"
    f\"{act.get('suggest', '<no suggestion>')}\"
)
print(json.dumps({'systemMessage': msg}))
" 2>/dev/null || echo '{}'

exit 0
