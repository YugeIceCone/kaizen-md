#!/usr/bin/env bash
# SessionStart hook — surface cached token-bloat findings (if any).
# Reads the cache file written by SessionEnd's scan; emits ONE LINE
# as additionalContext when findings exist. Empty {} otherwise.
#
# Designed to add zero noise when the plugin is clean.
#
# Bypass: KAIZEN_TOKEN_BLOAT_DISABLE=1

set -uo pipefail

[ "${KAIZEN_TOKEN_BLOAT_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')

# Trace firing (iron-law: every-hook-script-traces-its-firing).
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" SessionStart-token-bloat 2>/dev/null || true

LINE=$(python3 "$PLUGIN_ROOT/scripts/index/token_bloat.py" surface 2>/dev/null || true)

if [ -z "$LINE" ]; then
    echo '{}'
    exit 0
fi

python3 -c "
import json, sys
line = sys.argv[1]
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName':     'SessionStart',
        'additionalContext': line,
    },
}))
" "$LINE"
exit 0
