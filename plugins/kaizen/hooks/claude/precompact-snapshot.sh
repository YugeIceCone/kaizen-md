#!/usr/bin/env bash
# PreCompact hook — snapshot workflow state before context compaction.
# Calls backup.sh create --label pre-compact.
# Allows compaction (emits empty JSON / no decision).

set -uo pipefail

# Bypass-knob iron-law compliance.
[ "${KAIZEN_PRECOMPACT_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

# Resolve plugin root (CLAUDE_PLUGIN_ROOT → KAIZEN_PLUGIN_ROOT → derived).
_HOOK_DIR="$(cd "$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Capture event JSON for trace, then discard
EVENT=$(cat 2>/dev/null || echo '{}')

printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" PreCompact

REPO=$(git rev-parse --show-toplevel 2>/dev/null) || { echo '{}'; exit 0; }
cd "$REPO" || { echo '{}'; exit 0; }

# Only snapshot if there's state worth saving
if [ ! -f ".kaizen.toml" ] && [ ! -d ".workflow" ]; then
    echo '{}'
    exit 0
fi

# Resolve backup.sh — try resolved plugin root first, then the legacy
# ~/.claude/ standalone install as a last-ditch fallback.
BACKUP_SH=""
for candidate in \
    "$PLUGIN_ROOT/scripts/ops/backup.sh" \
    "$HOME/.claude/scripts/ops/backup.sh"; do
    if [ -x "$candidate" ]; then
        BACKUP_SH="$candidate"
        break
    fi
done

BACKUP_OK=0
BACKUP_PATH=""
if [ -x "$BACKUP_SH" ]; then
    # Run synchronously — backup.sh is ~200ms for 25M, well within
    # the 5s hook timeout. Previously backgrounded (`&`) which caused
    # the systemMessage to lie ("snapshotted" fired before tarball
    # existed). Sync makes the message honest.
    if BACKUP_OUTPUT=$(bash "$BACKUP_SH" create --label "pre-compact-$(date -u +%H%M%S)" 2>&1); then
        BACKUP_OK=1
        # Extract the resolved tarball path from `✓ backup: <path>`
        BACKUP_PATH=$(printf '%s' "$BACKUP_OUTPUT" \
            | grep -oE '✓ backup: [^ ]+' \
            | head -n1 \
            | sed -E 's/^✓ backup: //')
    fi
    # Log output to /tmp (replaces the prior background redirect)
    printf '%s\n' "$BACKUP_OUTPUT" >/tmp/kaizen-precompact.log 2>/dev/null || true
fi

# Allow compaction (omit decision field). systemMessage only when the
# snapshot really happened — and references the real backup location.
python3 -c "
import json, os, sys
ok = '${BACKUP_OK}' == '1'
path = '${BACKUP_PATH}'.strip()
if ok and path:
    msg = f'kaizen: pre-compact snapshot → {path}'
    print(json.dumps({'systemMessage': msg}))
else:
    print('{}')
"
