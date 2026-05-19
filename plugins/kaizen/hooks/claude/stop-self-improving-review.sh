#!/usr/bin/env bash
# kaizen Stop hook — periodic memory-curation nudge.
# Fires every N stops (default 5). Surfaces /kaizen:self-improving
# review when the session has accumulated enough stops to be worth
# checking auto-memory promotion candidates.
#
# Bypass: KAIZEN_SELF_IMPROVING_REVIEW_DISABLE=1
# Cadence: KAIZEN_SELF_IMPROVING_EVERY_N=<int> (default 5)

set -uo pipefail

[ "${KAIZEN_SELF_IMPROVING_REVIEW_DISABLE:-}" = "1" ] && { echo '{}'; exit 0; }

_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../skills/workflow/scripts/_plugin_root.sh
source "$_HOOK_DIR/../../skills/workflow/scripts/_plugin_root.sh"
PLUGIN_ROOT="$(kaizen_plugin_root 2>/dev/null)" || { echo '{}'; exit 0; }

# Trace firing (iron-law).
EVENT_JSON="$(cat 2>/dev/null || echo '{}')"
printf '%s' "$EVENT_JSON" | bash "$PLUGIN_ROOT/hooks/claude/_trace.sh" Stop-self-improving 2>/dev/null || true

python3 "$PLUGIN_ROOT/scripts/handlers/stop_self_improving_review.py" check 2>/dev/null \
    || echo '{}'
