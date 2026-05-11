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

INPUT=$(cat 2>/dev/null || echo "{}")

# kaizen-trace (non-blocking)
printf '%s' "$INPUT" | python3 "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/trace.py" \
    event --src hook --evt PostToolUse-drain >/dev/null 2>&1 || true

DRAINED=$(python3 "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/inbox.py" drain 2>/dev/null || echo "")

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
