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

# kaizen-trace (non-blocking)
printf '%s' "$INPUT" | python3 "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/trace.py" \
    event --src hook --evt UserPromptSubmit >/dev/null 2>&1 || true

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
    python3 "${CLAUDE_PLUGIN_ROOT}/skills/kaizen/scripts/inbox.py" \
        capture --session "$SESSION" "$PROMPT" >/dev/null 2>&1 || true
fi

exit 0
