#!/bin/bash

# Ralph Loop Stop Hook — Claude Code variant
# Continues the session with the original prompt while loop state is active.
# Reads .kaizen/loop.state.md (shared with the Codex variant at
# hooks/codex/stop-ralph.sh). The CC and Codex Stop-hook JSON contracts are
# identical (`decision:"block", reason, systemMessage`); this variant inspects
# CLAUDE_SESSION_ID / session_id, while the Codex variant inspects CODEX_*.
#
# Silent no-op when .kaizen/loop.state.md is absent — does not interfere with
# normal CC sessions.

set -euo pipefail

HOOK_INPUT=$(cat)

frontmatter_value() {
  local key="$1"
  printf '%s\n' "$FRONTMATTER" | sed -n "s/^${key}:[[:space:]]*//p" | head -n 1
}

json_stop() {
  local reason="$1"
  jq -n --arg reason "$reason" '{continue: false, stopReason: $reason}'
}

# CC hook inputs: `cwd`, `session_id`, and the assistant's last reply via
# `transcript_path` (jsonl). We read both `last_assistant_message` (if the
# kaizen wrapper pre-injects it) and fall back to scanning the transcript.
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

if [[ "$COMPLETION_PROMISE" != "null" ]] && [[ -n "$COMPLETION_PROMISE" ]]; then
  PROMISE_TEXT=$(printf '%s' "$LAST_OUTPUT" | perl -0777 -pe 's/.*?<promise>(.*?)<\/promise>.*/$1/s; s/^\s+|\s+$//g; s/\s+/ /g' 2>/dev/null || printf '')
  if [[ -n "$PROMISE_TEXT" ]] && [[ "$PROMISE_TEXT" == "$COMPLETION_PROMISE" ]]; then
    rm -f "$RALPH_STATE_FILE"
    json_stop "Ralph loop completed: completion promise matched."
    exit 0
  fi
fi

PROMPT_TEXT=$(awk '
  BEGIN { delimiters = 0 }
  /^---$/ { delimiters++; next }
  delimiters >= 2 { print }
' "$RALPH_STATE_FILE")

PROMPT_TEXT=$(printf '%s' "$PROMPT_TEXT" | perl -0777 -pe 's/\A\s+//; s/\s+\z//')

if [[ -z "$PROMPT_TEXT" ]]; then
  rm -f "$RALPH_STATE_FILE"
  json_stop "Ralph loop state invalid: prompt body is empty."
  exit 0
fi

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
  SYSTEM_MSG="Ralph iteration $NEXT_ITERATION. Stop only after outputting <promise>$COMPLETION_PROMISE</promise> truthfully."
else
  SYSTEM_MSG="Ralph iteration $NEXT_ITERATION."
fi

jq -n \
  --arg prompt "$PROMPT_TEXT" \
  --arg msg "$SYSTEM_MSG" \
  '{
    decision: "block",
    reason: $prompt,
    systemMessage: $msg
  }'
