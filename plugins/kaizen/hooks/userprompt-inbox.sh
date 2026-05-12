#!/usr/bin/env bash
# kaizen UserPromptSubmit hook: capture every user message into the inbox.
#
# Doesn't interrupt and doesn't inject — fires alongside the harness's
# normal prompt processing. The captured message becomes a durable record
# that the PostToolUse drain hook can surface back to Claude on the next
# tool-call boundary (so user input doesn't wait for a long sequence to
# finish).
#
# Read failure / empty prompt / missing python → exit 0 silently. We never
# block the user's prompt from reaching Claude.

set -uo pipefail

INPUT=$(cat 2>/dev/null || echo "{}")

printf '%s' "$INPUT" | bash "${CLAUDE_PLUGIN_ROOT}/hooks/_trace.sh" UserPromptSubmit

PROMPT=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('prompt') or d.get('user_prompt') or d.get('message') or '')
except Exception:
    pass
" 2>/dev/null)

SESSION=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('session_id') or '')
except Exception:
    pass
" 2>/dev/null)

if [ -n "${PROMPT:-}" ]; then
    INBOX="${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/inbox.py"
    # Capture prints the absolute path of the new message file
    CAPTURED=$(python3 "$INBOX" capture --session "$SESSION" "$PROMPT" 2>/dev/null) || true
    # Mark this as the turn-starter ONLY if no sentinel exists. Mid-turn
    # prompts (typed while Claude is busy) do NOT overwrite the sentinel,
    # so they surface normally on the next PostToolUse drain. The Stop
    # hook clears the sentinel at turn end.
    if [ -n "$CAPTURED" ]; then
        python3 "$INBOX" set-turn-starter "$CAPTURED" >/dev/null 2>&1 || true
    fi
fi

exit 0
