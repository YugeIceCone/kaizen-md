#!/usr/bin/env bash
# kaizen-blueprint dispatch — reusable subagent dispatch helper.
#
# Wraps the prepare → Agent() → finalize cycle for a single chunk:
#
#   prepare  — create isolated worktree, generate canonical prompt,
#              emit a meta block the parent agent feeds to Agent().
#   finalize — capture subagent commits, flip blueprint task statuses,
#              optionally clean up the worktree.
#
# The Agent() call itself is parent-side (Claude Code's tool). This
# script handles everything BEFORE and AFTER so dispatch is
# reproducible: same chunk + same plan = same worktree name + same
# prompt + same finalize.
#
# Usage:
#   dispatch.sh prepare <plan-file> --list-id X --chunk N \
#                                   [--agent-type kaizen-implementer] \
#                                   [--worktree-root <dir>]
#   dispatch.sh finalize <plan-file> --list-id X --chunk N \
#                                    --worktree <path> \
#                                    [--all-shipped | --task <id>:<status>]+ \
#                                    [--cleanup]

set -euo pipefail

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_SCRIPT_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
PLUGIN_ROOT="$(cd "$_SCRIPT_DIR/../.." && pwd)"
BLUEPRINT_PY="$PLUGIN_ROOT/scripts/blueprint/blueprint.py"

VERB="${1:-}"; shift || true
[ -z "$VERB" ] && { echo "usage: dispatch.sh {prepare|finalize} ..." >&2; exit 2; }

# ─── arg parser (shared) ────────────────────────────────────────────────

PLAN=""; LIST_ID=""; CHUNK_NUM=""; AGENT_TYPE="kaizen-implementer"
WORKTREE_ROOT=""; WORKTREE=""; CLEANUP=0; ALL_SHIPPED=0
declare -a TASK_UPDATES=()
PLAN="${1:-}"; [ -n "$PLAN" ] && shift || true

while [ $# -gt 0 ]; do
    case "$1" in
        --list-id)       LIST_ID="$2"; shift 2 ;;
        --chunk)         CHUNK_NUM="$2"; shift 2 ;;
        --agent-type)    AGENT_TYPE="$2"; shift 2 ;;
        --worktree-root) WORKTREE_ROOT="$2"; shift 2 ;;
        --worktree)      WORKTREE="$2"; shift 2 ;;
        --cleanup)       CLEANUP=1; shift ;;
        --all-shipped)   ALL_SHIPPED=1; shift ;;
        --task)          TASK_UPDATES+=("$2"); shift 2 ;;
        *) echo "unknown flag: $1" >&2; exit 2 ;;
    esac
done

[ -z "$PLAN" ] && { echo "missing plan file" >&2; exit 2; }
[ -f "$PLAN" ] || { echo "plan not found: $PLAN" >&2; exit 2; }
PLAN="$(readlink -f "$PLAN")"
REPO_ROOT="$(git -C "$(dirname "$PLAN")" rev-parse --show-toplevel 2>/dev/null \
             || cd "$(dirname "$PLAN")" && pwd)"
WORKTREE_ROOT="${WORKTREE_ROOT:-$REPO_ROOT/.claude/worktrees}"

# Deterministic chunk-id from list-id + chunk-num. Used for worktree
# name + branch so re-running prepare with the same args lands at the
# same location (idempotent).
CHUNK_ID="${LIST_ID}-c${CHUNK_NUM}"

# ─── prepare ────────────────────────────────────────────────────────────

cmd_prepare() {
    [ -z "$LIST_ID" ] && { echo "--list-id required" >&2; exit 2; }
    [ -z "$CHUNK_NUM" ] && { echo "--chunk required" >&2; exit 2; }

    # Fetch the chunk's tasks via the blueprint CLI (1 roundtrip).
    local chunk_json task_ids
    chunk_json="$(python3 "$BLUEPRINT_PY" chunk "$PLAN" \
                   --list-id "$LIST_ID" --subagents --json)"
    # Pick the Nth chunk (1-indexed for human friendliness).
    task_ids="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
chunks = data.get('chunks', [])
n = int(sys.argv[2]) - 1
if n < 0 or n >= len(chunks):
    print(f'chunk {n+1} out of range (1..{len(chunks)})', file=sys.stderr)
    sys.exit(2)
print(','.join(t['id'] for t in chunks[n]))
" "$chunk_json" "$CHUNK_NUM")"
    [ -z "$task_ids" ] && { echo "no tasks in chunk $CHUNK_NUM" >&2; exit 2; }

    # Create worktree (idempotent — reuse if branch already exists).
    local worktree="$WORKTREE_ROOT/$CHUNK_ID"
    local branch="kaizen-chunk/$CHUNK_ID"
    mkdir -p "$WORKTREE_ROOT"
    if [ -d "$worktree" ]; then
        echo "  ∘ worktree already exists at $worktree (reusing)" >&2
    else
        git -C "$REPO_ROOT" worktree add -b "$branch" "$worktree" HEAD \
            >/dev/null 2>&1 || \
        git -C "$REPO_ROOT" worktree add "$worktree" "$branch" >/dev/null
        echo "  ✓ created worktree at $worktree on branch $branch" >&2
    fi

    # Emit the canonical prompt to a file for Agent() consumption.
    local prompt_file="$worktree/.dispatch-prompt.md"
    cat > "$prompt_file" <<EOF
# Chunk dispatch — $CHUNK_ID

You are dispatched as a $AGENT_TYPE subagent in an isolated git
worktree. Your scope is the tasks listed below — nothing else.

## Working directory

\`$worktree\` (branch \`$branch\`)

Do NOT cd to the repo root. Do NOT edit through symlinks. All work
happens here.

## Plan

Source plan: \`$PLAN\`

Read the plan with the blueprint CLI (1-roundtrip per call):

\`\`\`bash
kaizen-blueprint show --id $LIST_ID --md         # the task-list this chunk belongs to
kaizen-blueprint show --id <task-id>              # any individual task ref
\`\`\`

## Your tasks (in order)

$(echo "$task_ids" | tr ',' '\n' | while read tid; do
    echo "- \`$tid\` — see plan for subject/refs"
done)

## TDD discipline

For each task: RED test → GREEN impl → commit.
Per task = one commit. Commit subject prefix: \`feat($CHUNK_ID-$tid):\`.

## What you ARE allowed to do

- Read / Edit / Write / Glob / Grep / safe Bash inside this worktree
- \`git add\`, \`git commit\`, \`git status\`, \`git diff\`, \`git log\`,
  \`git show\`, \`git worktree\`, \`git mv\`, \`git restore <file>\`
- \`python3\`, \`bash\`, \`chmod\`, \`mkdir\`, \`ls\`, \`cat\`, \`head\`,
  \`tail\`, \`grep\`, \`find\`, \`wc\`
- All \`kaizen-*\` plugin bins (including \`kaizen-blueprint\`)

## What you must NEVER do

- \`git push\`, \`git reset --hard\`, \`git checkout <other-branch>\`,
  \`git merge\`, \`git rebase\`, \`git clean\`, \`git branch -D|-d\`,
  \`git remote\`, \`rm -rf\`, \`curl\`, \`wget\`
- Edit files OUTSIDE this worktree
- Touch master directly — the parent will merge after all chunks settle

## When you finish

Report back:
- The branch (\`$branch\`)
- The commits you landed (\`git log --oneline HEAD ^master\`)
- Any tasks you couldn't complete + why
- Test baseline (\`python3 -m unittest discover ... | tail -3\`)

Parent will run \`kaizen-blueprint dispatch finalize ...\` to flip
task statuses + optionally clean up the worktree.
EOF

    # Machine-readable meta block on stdout.
    cat <<EOF
WORKTREE=$worktree
BRANCH=$branch
TASKS=$task_ids
PROMPT_FILE=$prompt_file
AGENT_TYPE=$AGENT_TYPE
ISOLATION=worktree
EOF
}

# ─── finalize ───────────────────────────────────────────────────────────

cmd_finalize() {
    [ -z "$LIST_ID" ] && { echo "--list-id required" >&2; exit 2; }
    [ -z "$WORKTREE" ] && { echo "--worktree required" >&2; exit 2; }
    [ -d "$WORKTREE" ] || { echo "worktree not found: $WORKTREE" >&2; exit 2; }

    # Mark tasks
    if [ "$ALL_SHIPPED" = "1" ]; then
        # Re-fetch the chunk to learn which task IDs to flip.
        local chunk_json task_ids
        chunk_json="$(python3 "$BLUEPRINT_PY" chunk "$PLAN" \
                       --list-id "$LIST_ID" --subagents --json)"
        task_ids="$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
chunks = data.get('chunks', [])
n = int(sys.argv[2]) - 1
print(','.join(t['id'] for t in chunks[n]))
" "$chunk_json" "$CHUNK_NUM")"
        for tid in ${task_ids//,/ }; do
            python3 "$BLUEPRINT_PY" set-task-status "$PLAN" \
              --task-id "$tid" --status completed
        done
    else
        for entry in "${TASK_UPDATES[@]}"; do
            local tid="${entry%%:*}"
            local status="${entry##*:}"
            python3 "$BLUEPRINT_PY" set-task-status "$PLAN" \
              --task-id "$tid" --status "$status"
        done
    fi

    # Report subagent commits (informational)
    local commits
    commits="$(git -C "$WORKTREE" log --oneline HEAD ^master 2>/dev/null || true)"
    if [ -n "$commits" ]; then
        echo "subagent commits on $WORKTREE:"
        echo "$commits" | sed 's/^/  /'
    fi

    # Optional cleanup
    if [ "$CLEANUP" = "1" ]; then
        git -C "$REPO_ROOT" worktree remove "$WORKTREE" 2>/dev/null \
          && echo "  ✓ worktree removed: $WORKTREE" \
          || echo "  ∘ worktree-remove failed (uncommitted changes? branch still active?)" >&2
    fi
}

case "$VERB" in
    prepare)  cmd_prepare ;;
    finalize) cmd_finalize ;;
    *) echo "unknown verb: $VERB" >&2; exit 2 ;;
esac
