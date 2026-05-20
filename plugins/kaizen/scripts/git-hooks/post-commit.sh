#!/usr/bin/env bash
# kaizen post-commit git hook — runs lightweight per-commit upkeep.
#
# Best-effort: never blocks or errors (post-commit failures are noisy and
# can't reverse the commit).
#
# Two responsibilities, each independently bypassed:
#   1. Auto-regen progress.jsonl when progress.md was touched.
#      Bypass: KAIZEN_POSTCOMMIT_PROGRESS_REGEN_DISABLE=1
#   2. Auto-advance the active /kaizen:workflow stage.
#      Bypass: KAIZEN_POSTCOMMIT_ADVANCE_DISABLE=1
#
# Symlinked into .kaizen/hooks/post-commit by /kaizen:setup install.

set -uo pipefail

# Resolve plugin root via realpath (script is symlinked from .kaizen/hooks/)
_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_SCRIPTS_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
# Depth was ../../../ when this lived at skills/workflow/scripts/.
# After move to scripts/git-hooks/, plugin root is ../../ up.
PLUGIN_ROOT="$(cd "$_SCRIPTS_DIR/../.." && pwd)"

# Resolve repo root — env override wins (for tests / arbitrary cwd);
# else git rev-parse (real post-commit invocation).
if [ -n "${KAIZEN_PROJECT_ROOT_OVERRIDE:-}" ]; then
    REPO="$KAIZEN_PROJECT_ROOT_OVERRIDE"
else
    REPO=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
fi

# ── (1) progress.jsonl auto-regen ───────────────────────────────────
# When progress.md was touched, walk it + rewrite progress.jsonl in
# place. Keeps the .md / .jsonl pair honest without the agent having
# to remember a manual regen step (BK-056).
if [ "${KAIZEN_POSTCOMMIT_PROGRESS_REGEN_DISABLE:-}" != "1" ]; then
    # `--root` is essential — without it the root commit silently has no
    # diff against a non-existent parent, so the regen would never fire
    # on the very first commit in a repo. Also handles normal commits.
    if git -C "$REPO" diff-tree --no-commit-id --name-only -r --root HEAD 2>/dev/null \
        | grep -qx ".kaizen/workflow/progress.md"; then
        python3 "$PLUGIN_ROOT/scripts/util/progress_log.py" regen \
            --file "$REPO/.kaizen/workflow/progress.md" >&2 2>&1 || true
    fi
fi

# ── (2) workflow auto-advance ───────────────────────────────────────
[ "${KAIZEN_POSTCOMMIT_ADVANCE_DISABLE:-}" = "1" ] && exit 0
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
python3 "$PLUGIN_ROOT/scripts/workflow/workflow_runner.py" advance \
    >&2 2>&1 || true

exit 0
