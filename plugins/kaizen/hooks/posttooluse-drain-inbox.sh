#!/usr/bin/env bash
# kaizen PostToolUse hook: drain inbox into additionalContext so Claude
# sees user messages on the next tool boundary, not at end-of-sequence.
#
# How it works:
#   - inbox.py drain prints pending messages + marks them drained.
#   - We wrap the result in a JSON envelope with hookSpecificOutput.
#     additionalContext, which Claude Code injects as visible context
#     into Claude's next turn.
#
# Exit 0 silently if no pending messages — don't spam the conversation.

set -uo pipefail

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

INPUT=$(cat 2>/dev/null || echo "{}")

printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/hooks/_trace.sh" PostToolUse-drain

DRAINED=$(python3 "$PLUGIN_ROOT/skills/workflow/scripts/inbox.py" drain 2>/dev/null || echo "")

if [ -n "${DRAINED:-}" ]; then
    # Pass via env to avoid shell-quoting hazards in the prompt text
    DRAINED="$DRAINED" python3 -c "
import json, os
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PostToolUse',
        'additionalContext': os.environ.get('DRAINED', ''),
    },
}))
"
fi

exit 0
