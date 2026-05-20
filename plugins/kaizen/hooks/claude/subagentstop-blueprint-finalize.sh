#!/usr/bin/env bash
# SubagentStop hook — blueprint-dispatch finalize advisory.
#
# Detects when a Claude Code subagent dispatched via the blueprint
# CLI's dispatch.sh prepare flow has stopped, and emits a one-line
# system message to the parent suggesting the `finalize` call to
# flip task statuses + (optionally) clean up the worktree.
#
# Advisory only — never auto-mutates the blueprint. Finalize is a
# durable artifact change (status flips on the plan); the parent
# decides whether to run it.
#
# Detection: the subagent's cwd contains `.dispatch-prompt.md`
# (written by dispatch.sh prepare). Avoids false positives from
# generic Agent() dispatches that never touched the blueprint flow.
#
# Bypass: KAIZEN_BLUEPRINT_DISPATCH_DISABLE=1.

set -uo pipefail

[ "${KAIZEN_BLUEPRINT_DISPATCH_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

# Read the stdin payload once (subagent metadata from Claude Code).
# We need cwd or worktree from it; the schema varies by host so be
# defensive — fall back to no-op on parse failure.
STDIN_JSON="$(cat 2>/dev/null || true)"
[ -z "$STDIN_JSON" ] && { echo '{}'; exit 0; }

# Extract a candidate cwd from the JSON. Try a few keys; null-safe.
CWD="$(echo "$STDIN_JSON" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
for key in ('subagent_cwd', 'cwd', 'working_directory'):
    v = d.get(key)
    if v:
        print(v); sys.exit(0)
# Probe nested locations
sa = d.get('subagent') or {}
for key in ('cwd', 'working_directory'):
    v = sa.get(key) if isinstance(sa, dict) else None
    if v:
        print(v); sys.exit(0)
" 2>/dev/null)"

# Only act when the subagent ran inside a worktree-with-dispatch-prompt.
[ -z "$CWD" ] && { echo '{}'; exit 0; }
PROMPT_FILE="$CWD/.dispatch-prompt.md"
[ -f "$PROMPT_FILE" ] || { echo '{}'; exit 0; }

# Pull the chunk-id + plan-path from the prompt header. The first
# heading line shape is `# Chunk dispatch — <chunk-id>`. The plan
# path lives on a `Source plan: \`<path>\`` line.
CHUNK_ID="$(awk -F'— ' '/^# Chunk dispatch/{print $2; exit}' "$PROMPT_FILE")"
PLAN_PATH="$(awk -F'`' '/^Source plan:/{print $2; exit}' "$PROMPT_FILE")"

# Derive list-id + chunk-num from CHUNK_ID (format: <list-id>-c<N>).
LIST_ID="${CHUNK_ID%-c*}"
CHUNK_NUM="${CHUNK_ID##*-c}"

# Emit an additionalContext advisory the parent sees on next turn.
cat <<EOF
{
  "hookSpecificOutput": {
    "additionalContext": "subagent stopped in worktree $CWD — to finalize, run:\\n\\n    kaizen-blueprint dispatch finalize $PLAN_PATH --list-id $LIST_ID --chunk $CHUNK_NUM --worktree $CWD --all-shipped\\n\\nReview commits first: git -C $CWD log --oneline HEAD ^master"
  }
}
EOF
