#!/usr/bin/env bash
# Universal PostToolUse trace — fires for every tool (matcher '*').
#
# Companion to pretooluse-trace.sh. Captures tool completion +
# (when available) duration_ms. Same skip-Bash rule.
#
# Bypass: KAIZEN_METRICS_DISABLE=1

set -uo pipefail

if [ "${KAIZEN_METRICS_DISABLE:-}" = "1" ]; then
    echo '{}'
    exit 0
fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Single python3 spawn — posttooluse_trace.py does parse + tool_response
# extraction + trace.append_event in one process. Was 4 spawns.
python3 "$PLUGIN_ROOT/scripts/handlers/posttooluse_trace.py" \
    >/dev/null 2>&1 || true

echo '{}'
exit 0
