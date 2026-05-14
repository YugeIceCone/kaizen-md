#!/usr/bin/env bash
# PreToolUse hook — destructive-Bash-command gate + bash-discipline advisory.
# Reads event JSON on stdin; emits a hook-decision JSON on stdout:
#   - permissionDecision (ask) for a destructive op
#       (git rm / push --force / reset --hard / clean -fd / rm -rf)
#   - systemMessage for a bash-invocation-discipline advisory
#   - {} otherwise
#
# All gate logic lives in _bash_gate.py — ONE python3 invocation (H3 speed
# fix; the pre-collapse hook spawned up to 6 python3 per Bash call). The
# only other process is the shared _trace.sh helper.
#
# Bypass: KAIZEN_BASH_GATE_DISABLE=1

set -uo pipefail

if [ "${KAIZEN_BASH_GATE_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

# Resolve plugin root (CLAUDE_PLUGIN_ROOT → KAIZEN_PLUGIN_ROOT → derived).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')

printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" PreToolUse-bash Bash

# Single python3: extract command + destructive-op match + discipline scan
# + emit decision. Falls back to no-opinion if the script itself errors —
# the gate must never block the host hook flow.
printf '%s' "$EVENT" | python3 "$PLUGIN_ROOT/hooks/claude/_bash_gate.py" 2>/dev/null || echo '{}'
exit 0
