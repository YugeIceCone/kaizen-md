#!/usr/bin/env bash
# gold-precompact — surface un-promoted gold captures right before
# context compaction. Captures that fall out of context without being
# promoted are effectively lost; this is the last-chance nudge.
#
# Output shape: hooks.json PreCompact contract. Empty JSON when nothing
# to surface; {"systemMessage": "..."} when N>0 un-promoted entries
# exist for the current project.
#
# Bypass: KAIZEN_GOLD_DISABLE=1 — also honored by gold.py itself.
# Iron-law: fires _trace.sh for observability.

set -uo pipefail

if [ "${KAIZEN_GOLD_DISABLE:-}" = "1" ]; then
    echo '{}'
    exit 0
fi

_SCRIPT_REAL="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
  || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
_HOOK_DIR="$(cd "$(dirname "$_SCRIPT_REAL")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

EVENT=$(cat 2>/dev/null || echo '{}')
printf '%s' "$EVENT" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" \
    PreCompact-gold 2>/dev/null || true

# Count un-promoted entries. Best-effort: any failure → silent exit.
COUNT=$(python3 "$PLUGIN_ROOT/scripts/gold/gold.py" \
    list --unpromoted --json 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' \
    2>/dev/null || echo "0")

if [ "$COUNT" = "0" ] || [ -z "$COUNT" ]; then
    echo '{}'
    exit 0
fi

# Surface as systemMessage. Single line per user-UI convention.
python3 -c "
import json
print(json.dumps({
    'systemMessage': f'kaizen-gold: $COUNT un-promoted pattern(s) before compaction — '
                     f'review with \`kaizen gold list --unpromoted\` or '
                     f'promote with \`kaizen gold promote N --to <path> [--brain]\`'
}))
" 2>/dev/null || echo '{}'

exit 0
