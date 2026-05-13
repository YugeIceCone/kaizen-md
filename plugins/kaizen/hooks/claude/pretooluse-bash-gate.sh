#!/usr/bin/env bash
# PreToolUse hook — destructive-Bash-command gate.
# Reads event JSON on stdin; emits permissionDecision JSON on stdout.
#
# Blocks (deny) or prompts (ask) before Claude runs:
#   - `git rm`              → ask (use pre-deletion belief scan; user authorizes)
#   - `git push --force`    → ask (destructive on shared state)
#   - `git reset --hard`    → ask (destroys uncommitted work)
#   - `git clean -fd`       → ask (deletes untracked work)
#   - `rm -rf` outside /tmp → ask (likely destructive)
#
# Allowed silently:
#   - All other Bash commands

set -uo pipefail

# Resolve plugin root (CLAUDE_PLUGIN_ROOT → KAIZEN_PLUGIN_ROOT → derived).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Read event JSON from stdin
EVENT=$(cat 2>/dev/null || echo '{}')

printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" PreToolUse-bash Bash

# Extract command via python3 (already required for backlog.py)
COMMAND=$(printf '%s' "$EVENT" | python3 -c "
import json, sys
try:
    e = json.load(sys.stdin)
    print(e.get('tool_input', {}).get('command', ''))
except Exception:
    pass
" 2>/dev/null)

# Empty command → no opinion
[ -z "$COMMAND" ] && { echo '{}'; exit 0; }

# Match patterns. Order matters — most-specific first.
DECISION=""
REASON=""

# git rm — pre-deletion gate is the git-commit-time check; PreToolUse is
# the model-runs-command-time check. Same belief-scan logic.
if echo "$COMMAND" | grep -qE '(^|[^a-zA-Z])git[[:space:]]+rm[[:space:]]'; then
    # Quick belief scan
    BELIEF=""
    [ -f "$HOME/.claude/brain/Notes/pref-no-deletions.md" ] && BELIEF="$HOME/.claude/brain/Notes/pref-no-deletions.md"
    if [ -n "$BELIEF" ]; then
        DECISION="ask"
        REASON="\`git rm\` triggers the no-deletions belief at $BELIEF — confirm explicit user authorization before proceeding."
    fi

# git push --force / --force-with-lease — destructive on shared branches
elif echo "$COMMAND" | grep -qE 'git[[:space:]]+push.*--force([[:space:]]|$)'; then
    DECISION="ask"
    REASON="\`git push --force\` overwrites remote history. Confirm target branch + that no collaborator pushes will be lost."

# git reset --hard — destroys uncommitted work
elif echo "$COMMAND" | grep -qE 'git[[:space:]]+reset[[:space:]]+--hard'; then
    DECISION="ask"
    REASON="\`git reset --hard\` discards uncommitted changes. Confirm no local work will be lost (run \`git status\` first)."

# git clean -fd / -fdx — destroys untracked files
elif echo "$COMMAND" | grep -qE 'git[[:space:]]+clean[[:space:]]+-[fdx]+'; then
    DECISION="ask"
    REASON="\`git clean -fd\` deletes untracked files. Confirm none are in-progress work (e.g. new test files)."

# rm -rf on anything not under /tmp or temp dirs
elif echo "$COMMAND" | grep -qE 'rm[[:space:]]+-[rR][fF]?[[:space:]]'; then
    # Allow /tmp, /var/tmp, ~/.cache
    if ! echo "$COMMAND" | grep -qE 'rm[[:space:]]+-[rR][fF]?[[:space:]]+(/tmp|/var/tmp|~/?\.cache|\$TMPDIR|\$HOME/\.cache)'; then
        DECISION="ask"
        REASON="\`rm -rf\` outside /tmp / cache dirs — confirm path is not a source-of-truth (config, brain, plans/, .workflow/)."
    fi
fi

# Emit decision
if [ -n "$DECISION" ]; then
    python3 -c "
import json
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': '$DECISION',
        'permissionDecisionReason': '''$REASON''',
    }
}))
"
    exit 0
fi

# ─── Advisory: bash-invocation-discipline scan ───────────────────────
# When no destructive-op decision fired, scan for the 6 discipline rules.
# Emit systemMessage on warnings — Claude sees + self-corrects; never blocks.

SCANNER="$PLUGIN_ROOT/hooks/_bash_discipline_scan.py"
if [ -x "$SCANNER" ] || [ -f "$SCANNER" ]; then
    SCAN_OUT=$(python3 "$SCANNER" --command "$COMMAND" 2>/dev/null)
    HAS_WARNINGS=$(printf '%s' "$SCAN_OUT" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read() or '{}')
    print('yes' if d.get('warnings') else 'no')
except Exception:
    print('no')
" 2>/dev/null)
    if [ "$HAS_WARNINGS" = "yes" ]; then
        printf '%s' "$SCAN_OUT" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
ws = d.get('warnings', [])
lines = ['kaizen bash-discipline advisory ({} warning{}):'.format(len(ws), '' if len(ws) == 1 else 's')]
for w in ws:
    sev = w.get('severity', 'soft').upper()
    lines.append('  [{}] {}: {}'.format(sev, w.get('rule', '?'), w.get('message', '')))
print(json.dumps({'systemMessage': '\n'.join(lines)}))
"
        exit 0
    fi
fi

# Clean — no decision, no advisory.
echo '{}'
