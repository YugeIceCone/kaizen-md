#!/usr/bin/env bash
# PreCompact hook — snapshot workflow state before context compaction.
# Calls backup.sh create --label pre-compact.
# Allows compaction (emits empty JSON / no decision).

set -uo pipefail

# Capture event JSON for trace, then discard
EVENT=$(cat 2>/dev/null || echo '{}')

printf '%s' "$EVENT" | bash "${CLAUDE_PLUGIN_ROOT}/hooks/_trace.sh" PreCompact

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
cd "$REPO" || { echo '{}'; exit 0; }

# Only snapshot if there's state worth saving
if [ ! -f ".kaizen.toml" ] && [ ! -d ".workflow" ]; then
    echo '{}'
    exit 0
fi

# Resolve backup.sh — three search paths, in order:
#   1. ${CLAUDE_PLUGIN_ROOT}/skills/workflow/scripts/backup.sh (plugin install)
#   2. via readlink-f of this script's location → sibling ../skills/workflow/scripts/
#   3. ~/.claude/skills/workflow/scripts/backup.sh (standalone install)
_HOOK_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
BACKUP_SH=""
for candidate in \
    "${CLAUDE_PLUGIN_ROOT:-/__unset__}/skills/workflow/scripts/backup.sh" \
    "$_HOOK_DIR/../skills/workflow/scripts/backup.sh" \
    "$HOME/.claude/skills/workflow/scripts/backup.sh"; do
    if [ -x "$candidate" ]; then
        BACKUP_SH="$candidate"
        break
    fi
done

if [ -x "$BACKUP_SH" ]; then
    # Run in background so we don't block compaction past ~500ms budget
    bash "$BACKUP_SH" create --label "pre-compact-$(date -u +%H%M%S)" >/tmp/kaizen-precompact.log 2>&1 &
fi

# Allow compaction (omit decision field)
python3 -c "
import json
print(json.dumps({
    'systemMessage': 'kaizen: backlog/workflow state snapshotted to ~/.claude/backups/kaizen/ before compaction.'
}))
"
