#!/usr/bin/env bash
# kaizen auto-handoff Stop hook — when context crosses the
# user-chosen threshold (25/50/75/85), emit a systemMessage telling
# the agent to create the handoff before /compact.
#
# Fires once per session (dedupe via dxm event). Reads session-mode
# threshold; no-op when no session-mode or threshold is Disabled.
#
# Bypass: KAIZEN_AUTO_HANDOFF_DISABLE=1

set -uo pipefail
[ "${KAIZEN_AUTO_HANDOFF_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Trace firing (iron-law: every-hook-script-traces-its-firing).
EVENT_JSON="$(cat 2>/dev/null || echo '{}')"
printf '%s' "$EVENT_JSON" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" Stop-auto-handoff 2>/dev/null || true

# Single python3 spawn — auto_handoff.py does threshold check,
# dedupe, dxm event write, and JSON envelope emission.
python3 "$PLUGIN_ROOT/skills/workflow/scripts/auto_handoff.py" check 2>/dev/null \
    || echo '{}'
