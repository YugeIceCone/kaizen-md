#!/usr/bin/env bash
# brain-user-prompt — detect explicit "remember this" triggers in user
# prompts and surface a capture hint.
#
# When the user's prompt contains capture-intent phrases ("remember
# this", "save this", "for the record", "brain dump"), this hook emits
# a stderr breadcrumb telling the agent to invoke
# kaizen-brain capture <text> or the brain_capture MCP tool.
#
# This is ADVISORY — no auto-write. The user's actual prompt may not
# carry the text to capture (just the trigger). The agent decides
# what content to route. This is the canonical replacement for the
# retired user_prompt.js Node-side hook.
#
# Stdin: JSON envelope from Claude Code with {user_prompt: "..."}.
# Output: optional context-injection on stdout (single JSON line),
#         brief breadcrumb on stderr. Always exit 0.
#
# Bypass: KAIZEN_BRAIN_PROMPT_DISABLE=1

set -uo pipefail

if [ "${KAIZEN_BRAIN_PROMPT_DISABLE:-}" = "1" ]; then
    exit 0
fi

# Read stdin envelope; tolerate missing input.
INPUT="$(cat 2>/dev/null || true)"

# Resolve plugin root + trace this hook's firing (best-effort).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh" 2>/dev/null
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null || true)"
if [ -n "$PLUGIN_ROOT" ]; then
    printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
        UserPromptSubmit-brain-trigger 2>/dev/null || true
fi

# Extract prompt text via python (jq may not be installed).
PROMPT="$(python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read() or "{}")
except Exception:
    sys.exit(0)
print(d.get("user_prompt", d.get("prompt", "")))
' <<<"$INPUT" 2>/dev/null || echo "")"

if [ -z "$PROMPT" ]; then
    exit 0
fi

# Trigger-phrase detection. Each phrase is a substring (case-
# insensitive). When matched, surface a tiny advisory so the agent
# sees the capture intent.
TRIGGERS=(
    "remember this"
    "save this"
    "for the record"
    "brain dump"
    "remember that"
    "save that"
    "capture this"
)

LOWER="$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')"
for trigger in "${TRIGGERS[@]}"; do
    if [[ "$LOWER" == *"$trigger"* ]]; then
        echo "kaizen-brain: detected capture trigger ('$trigger') — consider invoking kaizen-brain capture or the brain_capture MCP tool" >&2
        break
    fi
done

exit 0
