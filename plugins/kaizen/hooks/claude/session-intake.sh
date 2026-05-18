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

# Trace firing (iron-law: every-hook-script-traces-its-firing).
EVENT_JSON="$(cat 2>/dev/null || echo '{}')"
printf '%s' "$EVENT_JSON" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" SessionStart-intake 2>/dev/null || true

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

# Phase 6 of /kaizen:workflow full-automation: prefill the QA wizard
# from persisted .kaizen/workflow.json if it exists. Helper emits an
# annotation block (empty when no config); concat into the body below.
PREFILL=""
if [ -f ".kaizen/workflow.json" ]; then
    PREFILL=$(python3 "$PLUGIN_ROOT/skills/workflow/scripts/_workflow_prefill.py" \
        --from ".kaizen/workflow.json" 2>/dev/null || echo "")
fi

# All gates clear → emit the intake prompt as additionalContext.
# Imperative language: the agent's contract is "ask first, work after".
PREFILL="$PREFILL" python3 -c "
import json, os
prefill = os.environ.get('PREFILL', '')
body = '''MANDATORY — session intake. Call AskUserQuestion with these 4 questions in ONE call, BEFORE the user's first prompt.

Q1 (single) mode: \"How should this kaizen session be run?\" header=\"Session mode\"
  Loop      | Iterative self-correcting loop
  Workflow  | Multi-stage routine (explore → analyze → plan → execute)
  Neither   | No loop/workflow scaffolding

Q2 (multi) coding-style: \"Which CODING-STYLE disciplines apply?\" header=\"Coding style\"
  Simplicity (KISS + YAGNI + DRY)
  Structure  (SOLID + SoC + LoD + Onion-DDD + Hexagonal + Clean + DIP + Bounded-Contexts)
  Process    (TDD + Boy-Scout + Convention)
  Karpathy 4

Q3 (multi) operational: \"Which OPERATIONAL disciplines apply?\" header=\"Operational\"
  Quality       (gatekeeper + iron-laws + karpathy + simplify + vibe-check)
  Security      (security-review + iron-laws + verify-before-execution)
  Brain hygiene (remember + reflect + memory-state + evolve)
  Plugin-dev    (plugin-development + plugin-pitfalls + iron-laws + writing-skills + command-development)

Q4 (single) auto-handoff: \"Auto-trigger a handoff at ___% context?\" header=\"Auto-handoff\"
  25% | 50% | 75% (recommended) | 85% | Disabled

Persist in ONE command — bundle id = lowercase label first word (e.g. \"Brain hygiene\" → brain-hygiene); merge Q2+Q3 picks into --bundles csv; omit --threshold for Disabled:

  Bash(kaizen-session-mode set <loop|workflow|neither> --bundles <csv> [--threshold <25|50|75|85>])

Bypass: KAIZEN_SESSION_INTAKE_DISABLE=1.
'''
if prefill:
    body = body + prefill
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': body,
    }
}))
"
