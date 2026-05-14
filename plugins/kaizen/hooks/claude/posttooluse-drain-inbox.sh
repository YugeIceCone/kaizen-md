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
#
# Bypass: KAIZEN_INBOX_DISABLE=1

set -uo pipefail

if [ "${KAIZEN_INBOX_DISABLE:-}" = "1" ]; then exit 0; fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

INPUT=$(cat 2>/dev/null || echo "{}")

printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" PostToolUse-drain

# Empty-inbox short-circuit (H1 speed fix) — this hook fires on EVERY
# PostToolUse, but the inbox is empty the vast majority of the time.
# inbox.py writes one indented *.json per captured message; a pending one
# carries `"drained": false`. A single grep is ~10x cheaper than spawning
# python3 just to discover there's nothing to drain.
# shellcheck source=../../skills/workflow/scripts/_paths.sh
source "$PLUGIN_ROOT/skills/workflow/scripts/_paths.sh"
if ! grep -q '"drained": false' "$KAIZEN_INBOX_DIR"/*.json 2>/dev/null; then
    exit 0
fi

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
