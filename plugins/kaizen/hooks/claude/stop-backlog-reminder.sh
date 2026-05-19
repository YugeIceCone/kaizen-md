#!/usr/bin/env bash
# Stop hook — gentle reminder if backlog has in_flight items at end-of-turn.
# Soft signal only — never blocks Claude from stopping by default.
#
# Enable hard-block via env: KAIZEN_STOP_BLOCK_INFLIGHT=1

set -uo pipefail

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Capture event JSON for trace, then discard
EVENT=$(cat 2>/dev/null || echo '{}')

printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" Stop

# Clear the inbox turn-starter sentinel — next UserPromptSubmit starts
# a fresh turn. Non-blocking, never raises.
python3 "$PLUGIN_ROOT/scripts/intent/inbox.py" \
    clear-turn-starter >/dev/null 2>&1 || true

# Single python3 spawn — stop_backlog_reminder.py does repo
# resolution, backlog discovery, in_flight scan, and JSON emission
# in one process. Was 3 spawns (count + titles + final-JSON), plus
# the redundant shell-side toml grep+sed. The helper also adds a
# KAIZEN_BACKLOG_DISABLE bypass for parity with sibling hooks.
python3 "$PLUGIN_ROOT/scripts/handlers/stop_backlog_reminder.py"
