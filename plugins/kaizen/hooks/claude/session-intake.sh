#!/usr/bin/env bash
# kaizen session-intake — SessionStart hook that asks the agent to QA
# the user for the session mode (loop / workflow / neither).
#
# Fires ONCE per session, only when:
#   - KAIZEN_SESSION_INTAKE_DISABLE is unset
#   - no .kaizen/session-mode.json exists yet
#   - no .kaizen/loop.state.md exists (loop already running → mode is "loop")
#   - no incomplete .kaizen/workflow/state.json (workflow running → mode is "workflow")
#
# Emits an additionalContext systemMessage instructing the agent to
# call AskUserQuestion as its FIRST action, then persist via
# `kaizen-session-mode set <choice>`. The instruction is imperative —
# the agent must not proceed with the user's request until the mode
# is recorded (or the user chooses Neither).
#
# Bypass: KAIZEN_SESSION_INTAKE_DISABLE=1

set -uo pipefail

[ "${KAIZEN_SESSION_INTAKE_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Resolve repo root — intake only fires inside a git project (so we
# have a stable .kaizen/ dir to write into).
REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
cd "$REPO" || { echo '{}'; exit 0; }

# Gate 1: mode already recorded for THIS session.
if [ -f ".kaizen/session-mode.json" ]; then
    echo '{}'; exit 0
fi

# Gate 2: an active loop is running — its state file IS the implicit mode.
if [ -f ".kaizen/loop.state.md" ]; then
    echo '{}'; exit 0
fi

# Gate 3: an in-progress workflow run — same logic.
if [ -f ".kaizen/workflow/state.json" ]; then
    INCOMPLETE=$(python3 -c "
import json, sys
try:
    s = json.load(open('.kaizen/workflow/state.json'))
    stages = s.get('stages') or []
    current = s.get('current', 0)
    print('1' if (stages and current < len(stages)) else '0')
except Exception:
    print('0')
" 2>/dev/null)
    if [ "$INCOMPLETE" = "1" ]; then
        echo '{}'; exit 0
    fi
fi

# All gates clear → emit the intake prompt as additionalContext.
# Imperative language: the agent's contract is "ask first, work after".
python3 -c "
import json
body = '''MANDATORY — session intake (kaizen-md plugin)

This session has no recorded mode. BEFORE responding to the user's
first prompt, call the AskUserQuestion tool with EXACTLY this question:

  question: \"How should this kaizen session be run?\"
  header:   \"Session mode\"
  options:
    - label: \"Loop\"
      description: \"Iterative self-correcting (ralph-loop). Best for greenfield with clear automated verification.\"
    - label: \"Workflow\"
      description: \"Multi-stage routine (explore → analyze → plan → execute). Best for non-trivial implementations.\"
    - label: \"Neither\"
      description: \"Proceed directly without loop/workflow scaffolding.\"

After the user picks, record the choice and proceed:

  Bash(kaizen-session-mode set <loop|workflow|neither>)

Only AFTER recording the mode, address the user's original request.

To skip this intake permanently set KAIZEN_SESSION_INTAKE_DISABLE=1.
'''
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': body,
    }
}))
"
