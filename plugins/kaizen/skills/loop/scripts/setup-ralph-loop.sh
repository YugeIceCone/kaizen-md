#!/bin/bash

# Ralph Loop Setup Script
# Creates loop state for a Codex Stop hook.

set -euo pipefail

PROMPT_PARTS=()
MAX_ITERATIONS=0
COMPLETION_PROMISE="null"

die() {
  echo "Error: $*" >&2
  exit 1
}

escape_yaml_double_quoted() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -h|--help)
      cat << 'HELP_EOF'
Ralph Loop - Codex self-correcting Stop-hook loop

USAGE:
  /ralph-loop [PROMPT...] [OPTIONS]

ARGUMENTS:
  PROMPT...    Initial prompt to start the loop (can be multiple words without quotes)

OPTIONS:
  --max-iterations <n>           Maximum iterations before auto-stop (default: unlimited)
  --completion-promise '<text>'  Promise phrase (USE QUOTES for multi-word)
  -h, --help                     Show this help message

DESCRIPTION:
  Writes .codex/ralph-loop.local.md for the Ralph Stop hook.
  The Stop hook reads that file and continues the session with the same
  prompt until a completion promise matches or the iteration limit is reached.

  To signal completion, you must output: <promise>YOUR_PHRASE</promise>

EXAMPLES:
  /ralph-loop Build a todo API --completion-promise 'DONE' --max-iterations 20
  /ralph-loop --max-iterations 10 Fix the auth bug
  /ralph-loop Refactor cache layer  (runs forever)
  /ralph-loop --completion-promise 'TASK COMPLETE' Create a REST API

STOPPING:
  Use /cancel-ralph to remove the state file manually, or let the hook stop
  after --max-iterations or --completion-promise.

MONITORING:
  # View current iteration:
  grep '^iteration:' .codex/ralph-loop.local.md

  # View full state:
  head -10 .codex/ralph-loop.local.md
HELP_EOF
      exit 0
      ;;
    --max-iterations)
      if [[ -z "${2:-}" ]]; then
        die "--max-iterations requires a number"
      fi
      if ! [[ "$2" =~ ^[0-9]+$ ]]; then
        die "--max-iterations must be a non-negative integer"
      fi
      MAX_ITERATIONS="$2"
      shift 2
      ;;
    --completion-promise)
      if [[ -z "${2:-}" ]]; then
        die "--completion-promise requires text"
      fi
      COMPLETION_PROMISE="$2"
      shift 2
      ;;
    *)
      PROMPT_PARTS+=("$1")
      shift
      ;;
  esac
done

PROMPT="${PROMPT_PARTS[*]:-}"

if [[ -z "$PROMPT" ]]; then
  die "No prompt provided"
fi

mkdir -p .codex

if [[ -n "$COMPLETION_PROMISE" ]] && [[ "$COMPLETION_PROMISE" != "null" ]]; then
  COMPLETION_PROMISE_YAML="\"$(escape_yaml_double_quoted "$COMPLETION_PROMISE")\""
else
  COMPLETION_PROMISE_YAML="null"
fi

cat > .codex/ralph-loop.local.md <<EOF
---
active: true
iteration: 1
session_id: ${CODEX_SESSION_ID:-}
last_turn_id: ""
max_iterations: $MAX_ITERATIONS
completion_promise: $COMPLETION_PROMISE_YAML
started_at: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
---

$PROMPT
EOF

cat <<EOF
Ralph loop activated.

Iteration: 1
Max iterations: $(if [[ $MAX_ITERATIONS -gt 0 ]]; then echo $MAX_ITERATIONS; else echo "unlimited"; fi)
Completion promise: $(if [[ "$COMPLETION_PROMISE" != "null" ]]; then echo "${COMPLETION_PROMISE//\"/}"; else echo "none"; fi)

State file: .codex/ralph-loop.local.md

Ensure a Stop hook is installed and points to:
  ${CODEX_HOME:-$HOME/.codex}/skills/loop/hooks/stop-hook.sh

The hook will continue the session with the same prompt until the loop stops.

To monitor: head -10 .codex/ralph-loop.local.md
EOF

if [[ -n "$PROMPT" ]]; then
  echo ""
  echo "$PROMPT"
fi

if [[ "$COMPLETION_PROMISE" != "null" ]]; then
  echo ""
  echo "Completion rule:"
  echo ""
  echo "Output this exact text only when it is true:"
  echo "  <promise>$COMPLETION_PROMISE</promise>"
fi
