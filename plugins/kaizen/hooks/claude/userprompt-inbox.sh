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

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

INPUT=$(cat 2>/dev/null || echo "{}")

printf '%s' "$INPUT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" UserPromptSubmit

# Single python3 spawn — userprompt_inbox.py reads stdin once,
# extracts prompt + session_id, calls inbox.capture +
# inbox.set_turn_starter directly. Was 4 spawns (extract prompt +
# extract session + capture + set-turn-starter) per UserPromptSubmit.
printf '%s' "$INPUT" | python3 \
    "$PLUGIN_ROOT/skills/workflow/scripts/userprompt_inbox.py" \
    >/dev/null 2>&1 || true

exit 0
