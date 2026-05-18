#!/usr/bin/env bash
# kaizen post-commit git hook — auto-advance the active workflow stage.
# Phase 8 of /kaizen:workflow full-automation.
#
# Fires after every successful git commit. When .kaizen/workflow/state.json
# exists AND the schema isn't done, invokes `workflow_runner advance` so the
# state machine ticks forward in lock-step with the commit cadence.
#
# Best-effort: never blocks or errors (post-commit failures are noisy and
# can't reverse the commit).
#
# Bypass: KAIZEN_POSTCOMMIT_ADVANCE_DISABLE=1
#
# Symlinked into .kaizen/hooks/post-commit by /kaizen:setup install.

set -uo pipefail

[ "${KAIZEN_POSTCOMMIT_ADVANCE_DISABLE:-}" = "1" ] && exit 0

# Resolve plugin root via realpath (script is symlinked from .kaizen/hooks/)
_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_SCRIPTS_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
PLUGIN_ROOT="$(cd "$_SCRIPTS_DIR/../../.." && pwd)"

# Resolve repo root — env override wins (for tests / arbitrary cwd);
# else git rev-parse (real post-commit invocation).
if [ -n "${KAIZEN_PROJECT_ROOT_OVERRIDE:-}" ]; then
    REPO="$KAIZEN_PROJECT_ROOT_OVERRIDE"
else
    REPO=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
fi
STATE="$REPO/.kaizen/workflow/state.json"

[ -f "$STATE" ] || exit 0

# Is the schema already done? If so, no-op.
DONE=$(python3 -c "
import json
try:
    print('1' if json.load(open('$STATE')).get('done', False) else '0')
except Exception:
    print('1')  # treat malformed as done → don't try to advance
" 2>/dev/null)
[ "$DONE" = "1" ] && exit 0

# Advance the state machine. Output goes to stderr so the commit message
# stays clean in `git commit` UX.
cd "$REPO" || exit 0
python3 "$PLUGIN_ROOT/skills/workflow/scripts/workflow_runner.py" advance \
    >&2 2>&1 || true

exit 0
