#!/usr/bin/env bash
# SessionEnd hook — final inbox drain + session telemetry.
#
# Fires when a Claude Code session ends (close, restart, /clear). The
# hook body is additive:
#   1. Drains any remaining inbox messages so they aren't lost.
#   2. Writes a SessionEnd trace event with a one-line summary so
#      kaizen-trace can show per-session boundaries.
#
# Cross-CLI compat: SessionEnd is Claude-Code-specific. Hosts that
# don't fire it simply never invoke this script. Body is portable
# bash + Python stdlib.

set -uo pipefail

# Bypass-knob iron-law compliance.
[ "${KAIZEN_SESSIONEND_DRAIN_DISABLE:-}" = "1" ] && exit 0

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || exit 0

EVENT=$(cat 2>/dev/null || echo '{}')

# Trace the event boundary so search can scope queries to one session.
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" SessionEnd

# Final inbox drain — surface anything captured mid-session that
# didn't get a PostToolUse boundary to land on.
INBOX="$PLUGIN_ROOT/skills/workflow/scripts/inbox.py"
if [ -f "$INBOX" ]; then
    python3 "$INBOX" drain >/dev/null 2>&1 || true
    # Clear the turn-starter sentinel too; next session starts fresh.
    python3 "$INBOX" clear-turn-starter >/dev/null 2>&1 || true
fi

# One-line session telemetry — count in-flight backlog items at
# session-end as a quality signal (sessions that close with a lot
# of unfinished work flag for review).
REPO=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [ -n "$REPO" ] && [ -f "$REPO/.kaizen.toml" ]; then
    BACKLOG_MD=$(grep -E '^backlog_path' "$REPO/.kaizen.toml" 2>/dev/null \
        | head -1 \
        | sed -E 's/^[^=]*=[[:space:]]*"?([^"]*)"?.*$/\1/')
    if [ -n "$BACKLOG_MD" ]; then
        BACKLOG_JSON="$REPO/${BACKLOG_MD%.md}.json"
        if [ -f "$BACKLOG_JSON" ]; then
            INFLIGHT=$(python3 -c "
import json
try:
    d = json.load(open('$BACKLOG_JSON'))
    print(sum(1 for i in d.get('items',[]) if i.get('section') == 'in_flight'))
except Exception:
    print(0)
" 2>/dev/null)
            if [ "${INFLIGHT:-0}" != "0" ]; then
                python3 "$PLUGIN_ROOT/scripts/observe/trace.py" event \
                    --src hook --evt SessionEnd-inflight \
                    --data "{\"in_flight\":$INFLIGHT}" \
                    >/dev/null 2>&1 || true
            fi
        fi
    fi
fi

# Empty envelope; never blocks session close.
echo '{}'
