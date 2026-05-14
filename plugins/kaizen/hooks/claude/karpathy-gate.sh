#!/bin/bash
# Karpathy Gate — pre-commit hook (non-blocking)
#
# Runs complexity_checker and diff_surgeon on staged files. Prints warnings
# but does NOT block the commit — the goal is awareness, not enforcement.
#
# To install as a Husky pre-commit hook:
#   npx husky add .husky/pre-commit "bash path/to/karpathy-gate.sh"
#
# To install as a Claude Code PostToolUse hook (in .claude/settings.json):
#   {
#     "hooks": {
#       "PostToolUse": [{
#         "matcher": "Bash",
#         "hooks": [{
#           "type": "command",
#           "command": "${CLAUDE_PLUGIN_ROOT}/hooks/karpathy-gate.sh"
#         }]
#       }]
#     }
#   }

set -e

# Trace this hook's own firing (best-effort, never blocks).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || true)"
if [ -n "$_HOOK_DIR" ] && [ -f "$_HOOK_DIR/_trace.sh" ]; then
    echo '{}' | bash "$_HOOK_DIR/_trace.sh" karpathy-gate 2>/dev/null || true
fi

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"

# Only run on git commit operations
if [ -z "$(git diff --staged --name-only 2>/dev/null)" ]; then
    exit 0
fi

echo "--- Karpathy Gate ---"

# Get changed Python/TS files
CHANGED_FILES=$(git diff --staged --name-only --diff-filter=ACMR | grep -E '\.(py|ts|tsx|js|jsx)$' || true)

if [ -n "$CHANGED_FILES" ]; then
    echo "[simplicity] checking complexity..."
    for f in $CHANGED_FILES; do
        python3 "$SCRIPT_DIR/complexity_checker.py" "$f" --threshold medium 2>/dev/null | grep -E "^\s+\[WARN\]" || true
    done
fi

echo "[surgical] checking diff noise..."
python3 "$SCRIPT_DIR/diff_surgeon.py" 2>/dev/null | grep -E "Noise ratio:|Verdict:" || true

echo "--- /Karpathy Gate ---"
exit 0
