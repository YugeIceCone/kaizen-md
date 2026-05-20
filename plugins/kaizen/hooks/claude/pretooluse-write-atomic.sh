#!/usr/bin/env bash
# PreToolUse hook — intercept Write, route through _atomic.atomic_write.
# Backing logic lives in _write_atomic.py (single python3 invocation
# matching the bash-gate pattern).
#
# Bypass: KAIZEN_ATOMIC_WRITE_DISABLE=1

set -uo pipefail

# Hook is OPT-IN (default OFF) — see _write_atomic.py docstring.
# Without explicit ENABLE=1 the deny→error rendering creates noise.
if [ "${KAIZEN_ATOMIC_WRITE_ENABLE:-}" != "1" ]; then echo '{}'; exit 0; fi
if [ "${KAIZEN_ATOMIC_WRITE_DISABLE:-}" = "1" ]; then echo '{}'; exit 0; fi

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/util/_plugin_root.sh
source "$_HOOK_DIR/../../scripts/util/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')

# Trace firing (iron-law: every-hook-script-traces-its-firing).
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" PreToolUse-write-atomic Write

# Single python3: parse event, atomic-write, emit decision. Falls through
# (empty decision) on any error so CC's Write runs as fallback.
printf '%s' "$EVENT" | python3 "$PLUGIN_ROOT/scripts/handlers/_write_atomic.py" 2>/dev/null || echo '{}'
exit 0
