#!/bin/bash

# Ralph Loop Stop Hook — Claude Code variant
# Continues the session with the original prompt while loop state is active.
# Reads .kaizen/loop.state.md (shared with the Codex variant at
# hooks/codex/stop-ralph.sh) and delegates structured-ledger transitions to
# skills/workflow/scripts/loop_ledger.py (the cheat-proof verify gate).
#
# CC and Codex Stop-hook JSON contracts are identical (`decision:"block",
# reason, systemMessage`); this variant inspects CLAUDE_SESSION_ID, the
# Codex variant inspects CODEX_SESSION_ID. Both call the same ledger helper.
#
# Silent no-op when .kaizen/loop.state.md is absent — does not interfere
# with normal CC sessions.

set -euo pipefail

# Bypass-knob iron-law compliance.
[ "${KAIZEN_RALPH_LOOP_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-${KAIZEN_PLUGIN_ROOT:-}}"
if [[ -z "$PLUGIN_ROOT" ]]; then
  # Resolve from this script's location: hooks/claude/stop-ralph.sh → plugin/
  PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
LEDGER_HELPER="$PLUGIN_ROOT/skills/workflow/scripts/loop_ledger.py"

HOOK_INPUT=$(cat)

# Trace this hook's own firing (best-effort, never blocks the loop).
if [ -f "$PLUGIN_ROOT/hooks/claude/_trace.sh" ]; then
    printf '%s' "$HOOK_INPUT" \
        | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" Stop-ralph-loop 2>/dev/null || true
fi

frontmatter_value() {
  local key="$1"
  printf '%s\n' "$FRONTMATTER" | sed -n "s/^${key}:[[:space:]]*//p" | head -n 1
}

json_stop() {
  local reason="$1"
  jq -n --arg reason "$reason" '{continue: false, stopReason: $reason}'
}

HOOK_CWD=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // ""')
HOOK_SESSION=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // ""')
HOOK_TURN_ID=$(printf '%s' "$HOOK_INPUT" | jq -r '.turn_id // .transcript_path // ""')
LAST_OUTPUT=$(printf '%s' "$HOOK_INPUT" | jq -r '.last_assistant_message // ""')

if [[ -z "$LAST_OUTPUT" ]]; then
  TRANSCRIPT=$(printf '%s' "$HOOK_INPUT" | jq -r '.transcript_path // ""')
  if [[ -n "$TRANSCRIPT" ]] && [[ -f "$TRANSCRIPT" ]]; then
    LAST_OUTPUT=$(tac "$TRANSCRIPT" 2>/dev/null | jq -r 'select(.role=="assistant") | .content[0].text // .content // ""' 2>/dev/null | head -n 1 || printf '')
  fi
fi

if [[ -n "$HOOK_CWD" ]]; then
  RALPH_STATE_FILE="$HOOK_CWD/.kaizen/loop.state.md"
else
  RALPH_STATE_FILE=".kaizen/loop.state.md"
fi

if [[ ! -f "$RALPH_STATE_FILE" ]]; then
  exit 0
fi

FRONTMATTER=$(awk '
  BEGIN { delimiters = 0 }
  /^---$/ { delimiters++; next }
  delimiters == 1 { print }
  delimiters >= 2 { exit }
' "$RALPH_STATE_FILE")

ITERATION=$(frontmatter_value "iteration")
MAX_ITERATIONS=$(frontmatter_value "max_iterations")
COMPLETION_PROMISE=$(frontmatter_value "completion_promise")
STATE_SESSION=$(frontmatter_value "session_id")
STATE_LAST_TURN=$(frontmatter_value "last_turn_id")

COMPLETION_PROMISE=${COMPLETION_PROMISE#\"}
COMPLETION_PROMISE=${COMPLETION_PROMISE%\"}
STATE_SESSION=${STATE_SESSION#\"}
STATE_SESSION=${STATE_SESSION%\"}
STATE_LAST_TURN=${STATE_LAST_TURN#\"}
STATE_LAST_TURN=${STATE_LAST_TURN%\"}

# Session pinning — if the state file was written by a different session, no-op.
if [[ -n "$STATE_SESSION" ]] && [[ "$STATE_SESSION" != "$HOOK_SESSION" ]]; then
  exit 0
fi

if [[ ! "$ITERATION" =~ ^[0-9]+$ ]]; then
  rm -f "$RALPH_STATE_FILE"
  json_stop "Ralph loop state invalid: iteration must be numeric."
  exit 0
fi

if [[ ! "$MAX_ITERATIONS" =~ ^[0-9]+$ ]]; then
  rm -f "$RALPH_STATE_FILE"
  json_stop "Ralph loop state invalid: max_iterations must be numeric."
  exit 0
fi

# Idempotence — don't re-process the same turn (CC may fire Stop multiple times).
if [[ -n "$HOOK_TURN_ID" ]] && [[ -n "$STATE_LAST_TURN" ]] && [[ "$HOOK_TURN_ID" == "$STATE_LAST_TURN" ]]; then
  json_stop "Ralph loop already processed this turn."
  exit 0
fi

if [[ $MAX_ITERATIONS -gt 0 ]] && [[ $ITERATION -ge $MAX_ITERATIONS ]]; then
  rm -f "$RALPH_STATE_FILE"
  json_stop "Ralph loop stopped after reaching max_iterations=$MAX_ITERATIONS."
  exit 0
fi

# Structured-promise path (preferred — set by `loop_promise()` MCP tool
# or `kaizen-loop promise <phrase>`). Tool calls can't be confused with
# text mentions, so this is the unambiguous completion channel.
if [[ "$COMPLETION_PROMISE" != "null" ]] && [[ -n "$COMPLETION_PROMISE" ]]; then
  STRUCTURED_PROMISE=$(frontmatter_value "last_promise")
  STRUCTURED_PROMISE=${STRUCTURED_PROMISE#\"}
  STRUCTURED_PROMISE=${STRUCTURED_PROMISE%\"}
  if [[ -n "$STRUCTURED_PROMISE" ]] && [[ "$STRUCTURED_PROMISE" == "$COMPLETION_PROMISE" ]]; then
    rm -f "$RALPH_STATE_FILE"
    json_stop "Ralph loop completed: structured promise matched (via loop_promise tool)."
    exit 0
  fi
fi

# Text-promise fallback. Delegated to loop_ledger.py::check_completion_promise
# which strips markdown code fences and requires the promise tag at
# MESSAGE END — fixes the 2026-05-14 false-positive where a
# `<promise>X</promise>` token in a fenced code example wrongly ended a loop.
if [[ "$COMPLETION_PROMISE" != "null" ]] && [[ -n "$COMPLETION_PROMISE" ]]; then
  PROMISE_TMP=$(mktemp -t kaizen-loop-output-XXXX)
  printf '%s' "$LAST_OUTPUT" > "$PROMISE_TMP"
  if python3 "$LEDGER_HELPER" promise-check "$PROMISE_TMP" "$COMPLETION_PROMISE" 2>/dev/null; then
    rm -f "$PROMISE_TMP" "$RALPH_STATE_FILE"
    json_stop "Ralph loop completed: completion promise matched."
    exit 0
  fi
  rm -f "$PROMISE_TMP"
fi

# Delegate ledger transition + body update to the Python helper.
# Cheat-proof: the helper runs each pending item's `verify` and only moves
# items to `completed` when verify exits 0. Agent CANNOT write to completed.
DECISION=$(python3 "$LEDGER_HELPER" "$RALPH_STATE_FILE" "$ITERATION" 2>/dev/null || printf '{"action":"noop"}')
ACTION=$(printf '%s' "$DECISION" | jq -r '.action')
REASON=$(printf '%s' "$DECISION" | jq -r '.reason // ""')

case "$ACTION" in
  complete|complete-empty)
    rm -f "$RALPH_STATE_FILE"
    json_stop "$REASON"
    exit 0
    ;;
  noop)
    exit 0
    ;;
  block)
    # Increment iteration + record this turn so we don't re-process it.
    NEXT_ITERATION=$((ITERATION + 1))
    TEMP_FILE="${RALPH_STATE_FILE}.tmp.$$"
    TURN_ID_YAML="\"$HOOK_TURN_ID\""
    awk -v iteration="$NEXT_ITERATION" -v turn="$TURN_ID_YAML" '
      BEGIN { delimiters = 0 }
      /^---$/ { delimiters++; print; next }
      delimiters == 1 && /^iteration:/ { print "iteration: " iteration; next }
      delimiters == 1 && /^last_turn_id:/ { print "last_turn_id: " turn; next }
      { print }
    ' "$RALPH_STATE_FILE" > "$TEMP_FILE"
    mv "$TEMP_FILE" "$RALPH_STATE_FILE"

    if [[ "$COMPLETION_PROMISE" != "null" ]] && [[ -n "$COMPLETION_PROMISE" ]]; then
      SYSTEM_MSG="Ralph iteration $NEXT_ITERATION. Stop only after the ledger is empty OR after outputting <promise>$COMPLETION_PROMISE</promise> truthfully."
    else
      SYSTEM_MSG="Ralph iteration $NEXT_ITERATION. Edit .kaizen/loop.state.md to add or refine ledger items as you work; items move to completed only when their verify command exits 0."
    fi

    jq -n \
      --arg prompt "$REASON" \
      --arg msg "$SYSTEM_MSG" \
      '{
        decision: "block",
        reason: $prompt,
        systemMessage: $msg
      }'
    exit 0
    ;;
  *)
    # Unknown action from helper — fail safe (don't block).
    exit 0
    ;;
esac
