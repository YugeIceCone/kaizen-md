#!/usr/bin/env bash
# SessionEnd hook — refresh token-bloat findings cache.
# Cheap (<200ms over the whole plugin). Writes to
# $KAIZEN_DIR/token-bloat-findings.json so the next SessionStart's
# surface hook can show the agent fresh findings without rescanning.
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
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" SessionEnd-token-bloat 2>/dev/null || true

# Background the scan — SessionEnd should not block. Output discarded.
python3 "$PLUGIN_ROOT/skills/workflow/scripts/token_bloat.py" scan --cache \
    >/dev/null 2>&1 &

echo '{}'
exit 0
