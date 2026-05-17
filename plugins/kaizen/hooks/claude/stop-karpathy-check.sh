#!/usr/bin/env bash
# kaizen Stop hook — periodic karpathy complexity check on
# session-modified files. Fires at most once per session (dxm dedupe).
# Emits systemMessage when WARN-level complexity issues found.
#
# Bypass: KAIZEN_KARPATHY_STOP_DISABLE=1

set -uo pipefail

[ "${KAIZEN_KARPATHY_STOP_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Trace firing (iron-law).
EVENT_JSON="$(cat 2>/dev/null || echo '{}')"
printf '%s' "$EVENT_JSON" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" Stop-karpathy-check 2>/dev/null || true

python3 "$PLUGIN_ROOT/skills/workflow/scripts/stop_karpathy_check.py" check 2>/dev/null \
    || echo '{}'
