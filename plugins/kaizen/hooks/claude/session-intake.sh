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

# All gates clear → emit the intake prompt as additionalContext.
# Imperative language: the agent's contract is "ask first, work after".
python3 -c "
import json
body = '''MANDATORY — session intake (kaizen-md plugin)

This session has no recorded mode. BEFORE responding to the user's
first prompt, call the AskUserQuestion tool with EXACTLY these four
questions in a SINGLE call:

QUESTION 1 — mode (single-select):
  question: \"How should this kaizen session be run?\"
  header:   \"Session mode\"
  multiSelect: false
  options:
    - label: \"Loop\"
      description: \"Iterative self-correcting (ralph-loop). Best for greenfield with clear automated verification.\"
    - label: \"Workflow\"
      description: \"Multi-stage routine (explore → analyze → plan → execute). Best for non-trivial implementations.\"
    - label: \"Neither\"
      description: \"Proceed directly without loop/workflow scaffolding.\"

QUESTION 2 — coding-style disciplines (multiSelect):
  question: \"Which CODING-STYLE disciplines should be enforced this session?\"
  header:   \"Coding style\"
  multiSelect: true
  options:
    - label: \"Simplicity (KISS + YAGNI + DRY)\"
      description: \"Anti-bloat — small code, no premature abstraction, no repetition.\"
    - label: \"Structure (SOLID + SoC + LoD + Onion-DDD + Hexagonal + Clean + DIP + Bounded-Contexts)\"
      description: \"Architecture — layered systems, inward-only deps, ports & adapters, bounded contexts.\"
    - label: \"Process (TDD + Boy-Scout + Convention)\"
      description: \"How-you-work — test-first, leave it cleaner, follow existing patterns.\"
    - label: \"Karpathy 4\"
      description: \"Code-as-communication — readable intent over clever density.\"

QUESTION 3 — operational disciplines (multiSelect):
  question: \"Which OPERATIONAL disciplines should be cross-cutting this session?\"
  header:   \"Operational\"
  multiSelect: true
  options:
    - label: \"Quality (gatekeeper + iron-laws + karpathy + simplify + vibe-check)\"
      description: \"Audit/review surface — auto-run gatekeeper + lint disciplines proactively.\"
    - label: \"Security (security-review + iron-laws + verify-before-execution)\"
      description: \"OWASP-style scan + verify-before-execute gates on risky operations.\"
    - label: \"Brain hygiene (remember + reflect + memory-state + evolve)\"
      description: \"Second Brain upkeep — capture / reflect / promote beliefs throughout session.\"
    - label: \"Plugin-dev (plugin-development + plugin-pitfalls + iron-laws + writing-skills + command-development)\"
      description: \"kaizen plugin authoring — canonical feature shape + iron laws + skill/command conventions.\"

QUESTION 4 — auto-handoff context-pressure trigger (single-select):
  question: \"Auto-trigger a handoff when context window reaches ____ %?\"
  header:   \"Auto-handoff\"
  multiSelect: false
  options:
    - label: \"25%\"
      description: \"Paranoid — fire very early. Best for long iterative loops with lots of context churn.\"
    - label: \"50%\"
      description: \"Half-full — comfortable buffer. Good default for medium sessions.\"
    - label: \"75%\"
      description: \"Conservative — fire well before compact pressure. Recommended for most work.\"
    - label: \"85%\"
      description: \"Pushing it — fire only when context is genuinely tight.\"
    - label: \"Disabled\"
      description: \"No auto-handoff. Manually trigger via /kaizen:handoff create when ready.\"

After the user answers, persist ALL FOUR choices in ONE command.
Merge picks from BOTH multiSelect questions (Q2 + Q3) into a single
--bundles CSV:

  Bash(kaizen-session-mode set <loop|workflow|neither> --bundles <csv> --threshold <25|50|75|85>)

Bundle name mapping (lowercase, comma-separated):
  Coding-style tier:
    Simplicity → simplicity   Structure → structure
    Process    → process      Karpathy 4 → karpathy
  Operational tier:
    Quality    → quality      Security  → security
    Brain hygiene → brain-hygiene
    Plugin-dev → plugin-dev

Threshold mapping (integer or omit for Disabled):
  25%/50%/75%/85% → pass numeric value via --threshold
  Disabled        → OMIT the --threshold flag entirely

Example: user picks Loop + (Simplicity, Process) + (Quality) + 75%:
  kaizen-session-mode set loop --bundles simplicity,process,quality --threshold 75

Only AFTER recording the choices, address the user's original request.

To skip this intake permanently set KAIZEN_SESSION_INTAKE_DISABLE=1.
'''
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': body,
    }
}))
"
